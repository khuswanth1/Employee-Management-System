"""Team management & project allocation.

Who may do what (all enforced here; the UI only mirrors it):
- founder: everything, in any branch.
- manager (permission `teams.manage`): create teams, pick the leader and members, allocate projects they own, review
  reports - for the teams they own (`Team.manager_id`).
- team leader (any employee/manager named as `Team.leader_id`): see the team, distribute tasks (see projects module),
  follow daily updates and blockers, report progress to the manager.
- HR: memberships, transfers and reassignment of people between teams/branches inside their branch scope.
- team members: read-only view of their own team and its projects; their work happens in tasks / daily updates.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, exists, func, or_, select, true

from app.access import can_manage_user, has_permission, same_branch
from app.common import PageParams, audit
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import as_utc, utcnow
from app.db.tenant_models import (
    Branch, DailyUpdate, Department, Milestone, Project, Task, Team, TeamMember, TeamProject, TeamReport, User,
)
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import notify
from app.modules.org.router import _release_cross_branch_lines
from app.modules.projects.router import get_project
from app.modules.teams import service as svc
from app.modules.teams.schemas import (
    LeaderIn, MembersIn, ProjectIn, ReassignIn, ReportIn, TeamCreate, TeamUpdate, TransferIn, UpdateReviewIn,
)
from app.modules.updates.router import ser as ser_update
from app.modules.webhooks.service import emit

router = APIRouter(prefix="/teams", tags=["teams"])


def team_user(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if ctx.role == "board_member":
        raise Forbidden("Board members have no access to team data")
    return ctx


# ---- access ---------------------------------------------------------------------------------

def _scope(ctx: Ctx):
    """SQL condition over `Team`: the teams the caller may see at all."""
    u = ctx.user
    member = exists().where(TeamMember.team_id == Team.id, TeamMember.user_id == u.id)
    if ctx.role == "founder":
        return true()
    if ctx.role == "hr":
        base = Team.branch_id == u.branch_id if u.branch_id is not None else true()
        return or_(base, member, Team.leader_id == u.id)
    return or_(Team.manager_id == u.id, Team.leader_id == u.id, member)


def _get_team(ctx: Ctx, team_id: int) -> Team:
    t = ctx.db.scalar(select(Team).where(Team.id == team_id, _scope(ctx)))
    if t is None:
        raise NotFound("Team not found")  # out-of-scope teams look non-existent
    return t


def _caps(ctx: Ctx, t: Team) -> dict:
    founder = ctx.role == "founder"
    owner = ctx.role == "manager" and t.manager_id == ctx.user.id and has_permission(ctx.user, "teams.manage")
    hr = ctx.role == "hr"
    lead = t.leader_id == ctx.user.id and t.is_active
    manage = founder or owner
    return {
        "can_manage": manage, "can_manage_members": manage or hr or lead, "can_lead": lead, "can_monitor": manage or hr or lead,
        "is_member": ctx.db.get(TeamMember, (t.id, ctx.user.id)) is not None,
    }


def _need(ctx: Ctx, t: Team, cap: str, message: str) -> dict:
    c = _caps(ctx, t)
    if not c[cap]:
        raise Forbidden(message)
    return c


def _manager_dep(ctx: Ctx = Depends(team_user)) -> Ctx:
    """Creating teams: founders, or managers holding the `teams.manage` permission."""
    if ctx.role == "founder":
        return ctx
    if ctx.role == "manager" and has_permission(ctx.user, "teams.manage"):
        return ctx
    raise Forbidden("Only a founder or a manager with the 'teams.manage' permission can create teams")


# ---- validation helpers ---------------------------------------------------------------------

def _people(ctx: Ctx, ids, roles, what: str) -> list[User]:
    ids = set(ids)
    if not ids:
        return []
    people = list(ctx.db.scalars(select(User).where(User.id.in_(ids))))
    if len(people) != len(ids):
        raise AppError("One or more people do not exist")
    for u in people:
        if not u.is_active or u.status == "offboarded":
            raise AppError(f"{u.full_name} is not an active employee")
        if u.role not in roles:
            raise AppError(f"{u.full_name} ({u.role.replace('_', ' ')}) cannot be {what}")
    return people


def _check_branch(ctx: Ctx, team_branch: int | None, people: list[User]) -> None:
    for u in people:
        if team_branch is not None and u.branch_id != team_branch:
            raise AppError(f"{u.full_name} does not belong to this team's branch")
        if ctx.role in ("manager", "hr") and not same_branch(ctx.user, u):
            raise AppError("You can only involve people from your own branch")


def _check_free(ctx: Ctx, team_id: int | None, ids) -> None:
    ids = list(set(ids))
    if not ids:
        return
    q = (select(User.full_name, Team.name).join(TeamMember, TeamMember.user_id == User.id)
         .join(Team, Team.id == TeamMember.team_id).where(TeamMember.user_id.in_(ids), Team.is_active.is_(True)))
    if team_id is not None:
        q = q.where(TeamMember.team_id != team_id)
    taken = ctx.db.execute(q).all()
    if taken:
        raise Conflict("; ".join(f"{n} is already in team {t}" for n, t in taken) + ". Use a transfer to move them.")


def _clear_stale(ctx: Ctx, ids, keep_team: int | None = None) -> None:
    """A membership of an *inactive* team does not block joining another team: drop it (the DB allows one row per person)."""
    ids = list(set(ids))
    if not ids:
        return
    rows = ctx.db.execute(select(TeamMember.team_id, TeamMember.user_id).join(Team, Team.id == TeamMember.team_id)
                          .where(TeamMember.user_id.in_(ids), Team.is_active.is_(False))).all()
    for tid, uid in rows:
        if tid != keep_team:
            svc.release_user(ctx.db, ctx.db.get(Team, tid), uid, unassign_tasks=False)


def _check_name(ctx: Ctx, name: str, exclude: int | None = None) -> None:
    q = select(Team.id).where(func.lower(Team.name) == name.lower())
    if exclude is not None:
        q = q.where(Team.id != exclude)
    if ctx.db.scalar(q) is not None:
        raise Conflict("A team with this name already exists")


def _check_branch_ref(ctx: Ctx, branch_id: int | None) -> None:
    if branch_id is None:
        return
    b = ctx.db.get(Branch, branch_id)
    if b is None:
        raise AppError("Branch does not exist")
    if not b.is_active:
        raise AppError("This branch is inactive")


def _check_manager(ctx: Ctx, manager_id: int | None, branch_id: int | None) -> User | None:
    if manager_id is None:
        return None
    m = ctx.db.get(User, manager_id)
    if m is None or not m.is_active or m.role != "manager":
        raise AppError("The team manager must be an active manager")
    if branch_id is not None and m.branch_id is not None and m.branch_id != branch_id:
        raise AppError("The team manager must belong to the team's branch")
    return m


def _join(ctx: Ctx, t: Team, users: list[User], *, announce: bool = True) -> None:
    """Add people to the team and give them access to every project allocated to it."""
    _clear_stale(ctx, [u.id for u in users], keep_team=t.id)
    for u in users:
        ctx.db.add(TeamMember(team_id=t.id, user_id=u.id))
    ctx.db.flush()
    svc.grant_project_access(ctx.db, svc.team_project_ids(ctx.db, t.id), [u.id for u in users])
    if announce:
        notify(ctx.db, [u.id for u in users if u.id != ctx.user.id], "Added to a team", f"You are now part of team {t.name}.", "team", f"/teams/{t.id}")


# ---- stats ----------------------------------------------------------------------------------

def _task_rows(ctx: Ctx, team_ids: list[int]):
    """(team, member, task) triples: tasks of team projects that are assigned to members of that team."""
    if not team_ids:
        return []
    return ctx.db.execute(
        select(TeamProject.team_id, TeamMember.user_id, Task.id, Task.project_id, Task.status, Task.due_date, Task.progress,
               Task.is_blocked, Task.approved_at, Task.updated_at)
        .select_from(Task).join(TeamProject, TeamProject.project_id == Task.project_id)
        .join(TeamMember, and_(TeamMember.team_id == TeamProject.team_id, TeamMember.user_id == Task.assignee_id))
        .where(TeamProject.team_id.in_(team_ids))
    ).all()


def _blank() -> dict:
    return {"total": 0, "done": 0, "open": 0, "overdue": 0, "blocked": 0, "progress_sum": 0, "done_30d": 0, "done_due": 0, "on_time": 0}


def _aggregate(rows) -> tuple[dict, dict]:
    today, cutoff = utcnow().date(), utcnow() - timedelta(days=30)
    by_team: dict[int, dict] = {}
    by_member: dict[tuple[int, int], dict] = {}
    for team_id, uid, _tid, _pid, status, due, progress, blocked, approved, updated in rows:
        for bucket in (by_team.setdefault(team_id, _blank()), by_member.setdefault((team_id, uid), _blank())):
            bucket["total"] += 1
            bucket["progress_sum"] += progress or 0
            if status == "done":
                bucket["done"] += 1
                finished = as_utc(approved or updated)
                if finished and finished >= cutoff:
                    bucket["done_30d"] += 1
                if due:
                    bucket["done_due"] += 1
                    if finished and finished.date() <= due:
                        bucket["on_time"] += 1
            else:
                bucket["open"] += 1
                if due and due < today:
                    bucket["overdue"] += 1
                if blocked:
                    bucket["blocked"] += 1
    return by_team, by_member


def _public_stats(s: dict | None) -> dict:
    s = s or _blank()
    return {
        "task_count": s["total"], "done_count": s["done"], "open_tasks": s["open"], "overdue_tasks": s["overdue"],
        "blocked_tasks": s["blocked"], "progress": round(s["progress_sum"] / s["total"]) if s["total"] else 0,
        "done_last_30d": s["done_30d"],
        "on_time_rate": round(100 * s["on_time"] / s["done_due"]) if s["done_due"] else None,
    }


def _names(ctx: Ctx, ids) -> dict[int, User]:
    ids = {i for i in ids if i}
    return {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _person(u: User | None) -> dict | None:
    return {"id": u.id, "full_name": u.full_name, "designation": u.designation, "avatar_v": u.avatar_name} if u else None


def ser_team(ctx: Ctx, t: Team, stats: dict, names: dict, counts: dict, projects: list | None = None, members: list | None = None) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description, "branch_id": t.branch_id, "department_id": t.department_id,
        "manager_id": t.manager_id, "leader_id": t.leader_id, "is_active": t.is_active, "created_at": t.created_at,
        "manager": _person(names.get(t.manager_id)), "leader": _person(names.get(t.leader_id)),
        "member_count": counts.get(t.id, (0, 0))[0], "project_count": counts.get(t.id, (0, 0))[1],
        "projects": projects or [],
        "members": members or [],
        **_public_stats(stats.get(t.id)), **{k: v for k, v in _caps(ctx, t).items()},
    }


def _counts(ctx: Ctx, ids: list[int]) -> dict:
    out = {i: [0, 0] for i in ids}
    for tid, n in ctx.db.execute(select(TeamMember.team_id, func.count()).where(TeamMember.team_id.in_(ids)).group_by(TeamMember.team_id)):
        out[tid][0] = n
    for tid, n in ctx.db.execute(select(TeamProject.team_id, func.count()).where(TeamProject.team_id.in_(ids)).group_by(TeamProject.team_id)):
        out[tid][1] = n
    return {k: tuple(v) for k, v in out.items()}


def _project_rows(ctx: Ctx, t: Team, monitor: bool) -> list[dict]:
    links = ctx.db.execute(select(TeamProject, Project).join(Project, Project.id == TeamProject.project_id)
                           .where(TeamProject.team_id == t.id).order_by(Project.name)).all()
    pids = [p.id for _, p in links]
    tasks: dict[int, list] = {}
    miles: dict[int, list] = {}
    detail: dict[tuple[int, int], list] = {}
    if pids:
        for pid, status, due, progress, assignee, tid, title, blocked, priority in ctx.db.execute(
                select(Task.project_id, Task.status, Task.due_date, Task.progress, Task.assignee_id, Task.id, Task.title, Task.is_blocked, Task.priority)
                .where(Task.project_id.in_(pids)).order_by(Task.due_date.is_(None), Task.due_date, Task.id)):
            tasks.setdefault(pid, []).append((status, due, progress, assignee))
            if assignee is not None:
                detail.setdefault((pid, assignee), []).append({
                    "id": tid, "title": title, "status": status, "due_date": due, "is_blocked": blocked,
                    "progress": progress, "priority": priority
                })
        for m in ctx.db.scalars(select(Milestone).where(Milestone.project_id.in_(pids)).order_by(Milestone.due_date, Milestone.id)):
            miles.setdefault(m.project_id, []).append(m)
    today = utcnow().date()
    roster = ctx.db.scalars(select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == t.id).order_by(User.full_name)).all()
    out = []
    for link, p in links:
        ts = tasks.get(p.id, [])
        ms = miles.get(p.id, [])
        pending = [m for m in ms if not m.completed]
        p_people = [{
            "id": u.id, "full_name": u.full_name, "designation": u.designation, "role": u.role, "avatar_v": u.avatar_name,
            "is_leader": u.id == t.leader_id, "tasks": detail.get((p.id, u.id), []),
            "task_count": len(detail.get((p.id, u.id), [])),
            "open_tasks": sum(1 for x in detail.get((p.id, u.id), []) if x["status"] != "done"),
            "done_tasks": sum(1 for x in detail.get((p.id, u.id), []) if x["status"] == "done"),
        } for u in roster]
        d = {
            "id": p.id, "name": p.name, "status": p.status, "start_date": p.start_date, "due_date": p.due_date, "owner_id": p.owner_id,
            "assigned_at": link.assigned_at, "task_count": len(ts), "done_count": sum(1 for x in ts if x[0] == "done"),
            "progress": round(sum(x[2] or 0 for x in ts) / len(ts)) if ts else 0,
            "milestones_total": len(ms), "milestones_done": len(ms) - len(pending),
            "next_milestone": {"title": pending[0].title, "due_date": pending[0].due_date} if pending else None,
            "people": p_people,
            "active_members": [m for m in p_people if m["task_count"] > 0],
        }
        if monitor:
            d["overdue_tasks"] = sum(1 for x in ts if x[0] != "done" and x[1] and x[1] < today)
            d["unassigned_tasks"] = sum(1 for x in ts if x[0] != "done" and x[3] is None)
            d["overdue_milestones"] = sum(1 for m in pending if m.due_date and m.due_date < today)
        out.append(d)
    return out


def _detail(ctx: Ctx, t: Team) -> dict:
    c = _caps(ctx, t)
    monitor = c["can_monitor"]
    memberships = ctx.db.scalars(select(TeamMember).where(TeamMember.team_id == t.id).order_by(TeamMember.joined_at)).all()
    ids = [m.user_id for m in memberships]
    names = _names(ctx, ids + [t.manager_id, t.leader_id])
    by_team, by_member = _aggregate(_task_rows(ctx, [t.id]))
    last_update: dict[int, date] = {}
    if monitor and ids:
        last_update = dict(ctx.db.execute(select(DailyUpdate.user_id, func.max(DailyUpdate.work_date)).where(DailyUpdate.user_id.in_(ids)).group_by(DailyUpdate.user_id)).all())
    members = []
    for m in memberships:
        u = names.get(m.user_id)
        if u is None:
            continue
        d = {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "designation": u.designation,
             "branch_id": u.branch_id, "avatar_v": u.avatar_name, "is_leader": u.id == t.leader_id, "joined_at": m.joined_at}
        if monitor:
            s = _public_stats(by_member.get((t.id, u.id)))
            d.update(open_tasks=s["open_tasks"], overdue_tasks=s["overdue_tasks"], blocked_tasks=s["blocked_tasks"],
                     done_count=s["done_count"], progress=s["progress"], last_update=last_update.get(u.id))
        members.append(d)
    projects = _project_rows(ctx, t, monitor)

    # Attach the projects and task details each member is working on
    for mem in members:
        uid = mem["id"]
        m_projs = []
        for p in projects:
            p_people = p.get("people", [])
            for person in p_people:
                if person["id"] == uid and (person.get("open_tasks", 0) > 0 or person.get("done_tasks", 0) > 0):
                    m_projs.append({"id": p["id"], "name": p["name"], "tasks_count": len(person.get("tasks", [])), "tasks": person.get("tasks", [])})
                    break
        mem["projects"] = m_projs
    out = {
        "id": t.id, "name": t.name, "description": t.description, "branch_id": t.branch_id, "department_id": t.department_id,
        "manager_id": t.manager_id, "leader_id": t.leader_id, "is_active": t.is_active, "created_at": t.created_at,
        "manager": _person(names.get(t.manager_id)), "leader": _person(names.get(t.leader_id)),
        "member_count": len(members), "project_count": len(projects), **_public_stats(by_team.get(t.id)), **c,
        "members": members, "projects": projects,
    }
    if monitor:
        out["blockers"] = _blockers(ctx, t, ids, names)
    return out


def _blockers(ctx: Ctx, t: Team, member_ids: list[int], names: dict) -> dict:
    tasks = []
    pids = svc.team_project_ids(ctx.db, t.id)
    if pids and member_ids:
        rows = ctx.db.scalars(select(Task).where(Task.project_id.in_(pids), Task.assignee_id.in_(member_ids), Task.is_blocked.is_(True), Task.status != "done").order_by(Task.id))
        tasks = [{"task_id": x.id, "title": x.title, "project_id": x.project_id, "assignee_id": x.assignee_id,
                  "assignee_name": names[x.assignee_id].full_name if x.assignee_id in names else None, "note": x.blocker_note} for x in rows]
    updates = []
    if member_ids:
        since = utcnow().date() - timedelta(days=3)
        rows = ctx.db.scalars(select(DailyUpdate).where(DailyUpdate.user_id.in_(member_ids), DailyUpdate.work_date >= since,
                                                        DailyUpdate.blockers.is_not(None)).order_by(DailyUpdate.work_date.desc()))
        updates = [{"update_id": u.id, "user_id": u.user_id, "full_name": names[u.user_id].full_name if u.user_id in names else None,
                    "work_date": u.work_date, "blockers": u.blockers} for u in rows if u.blockers and u.blockers.strip()]
    return {"tasks": tasks, "updates": updates}


# ---- teams: list / create / read / update / delete ---------------------------------------------

@router.get("")
def list_teams(q: str | None = None, branch_id: int | None = None, active: bool | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(team_user)):
    stmt = select(Team).where(_scope(ctx)).order_by(Team.name)
    if q:
        stmt = stmt.where(func.lower(Team.name).like(f"%{q.lower()}%"))
    if branch_id:
        stmt = stmt.where(Team.branch_id == branch_id)
    if active is not None:
        stmt = stmt.where(Team.is_active.is_(active))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = ctx.db.scalars(stmt.limit(params.page_size).offset((params.page - 1) * params.page_size)).all()
    ids = [t.id for t in rows]
    by_team, by_member = _aggregate(_task_rows(ctx, ids))

    # Pre-fetch projects and members for all teams in `ids`
    projects_by_team: dict[int, list] = {i: [] for i in ids}
    members_by_team: dict[int, list] = {i: [] for i in ids}
    if ids:
        mem_rows = ctx.db.execute(
            select(TeamMember.team_id, User)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id.in_(ids))
            .order_by(User.full_name)
        ).all()
        for tid, u in mem_rows:
            s = _public_stats(by_member.get((tid, u.id)))
            members_by_team[tid].append({
                "id": u.id, "full_name": u.full_name, "avatar_v": u.avatar_name,
                "role": u.role, "designation": u.designation, "is_leader": False,
                "open_tasks": s["open_tasks"], "done_count": s["done_count"], "progress": s["progress"]
            })

        proj_rows = ctx.db.execute(
            select(TeamProject.team_id, Project)
            .join(Project, Project.id == TeamProject.project_id)
            .where(TeamProject.team_id.in_(ids))
            .order_by(Project.name)
        ).all()
        all_pids = list({p.id for _, p in proj_rows})

        proj_tasks: dict[int, list] = {}
        if all_pids:
            for tid, title, st, due, prog, blk, prio, pid, aid in ctx.db.execute(
                select(Task.id, Task.title, Task.status, Task.due_date, Task.progress, Task.is_blocked, Task.priority, Task.project_id, Task.assignee_id)
                .where(Task.project_id.in_(all_pids))
            ):
                proj_tasks.setdefault(pid, []).append({
                    "id": tid, "title": title, "status": st, "due_date": due, "progress": prog,
                    "is_blocked": blk, "priority": prio, "assignee_id": aid
                })

        for tid, p in proj_rows:
            t_tasks = proj_tasks.get(p.id, [])
            team_mems = members_by_team.get(tid, [])
            p_members = []
            for u in team_mems:
                u_tasks = [x for x in t_tasks if x["assignee_id"] == u["id"]]
                p_members.append({
                    "id": u["id"], "full_name": u["full_name"], "avatar_v": u["avatar_v"],
                    "role": u["role"], "designation": u["designation"],
                    "task_count": len(u_tasks),
                    "open_tasks": sum(1 for x in u_tasks if x["status"] != "done"),
                    "done_tasks": sum(1 for x in u_tasks if x["status"] == "done"),
                    "tasks": [{"id": x["id"], "title": x["title"], "status": x["status"], "is_blocked": x["is_blocked"], "due_date": x.get("due_date"), "priority": x.get("priority"), "progress": x.get("progress")} for x in u_tasks]
                })

            p_progress = round(sum(x["progress"] or 0 for x in t_tasks) / len(t_tasks)) if t_tasks else 0
            projects_by_team[tid].append({
                "id": p.id, "name": p.name, "status": p.status, "progress": p_progress,
                "task_count": len(t_tasks), "done_count": sum(1 for x in t_tasks if x["status"] == "done"),
                "people": p_members,
                "active_members": [m for m in p_members if m["task_count"] > 0]
            })

    names = _names(ctx, [i for t in rows for i in (t.manager_id, t.leader_id)])
    counts = _counts(ctx, ids) if ids else {}
    return {
        "items": [ser_team(ctx, t, by_team, names, counts, projects_by_team.get(t.id, []), members_by_team.get(t.id, [])) for t in rows],
        "total": total, "page": params.page, "page_size": params.page_size
    }


@router.get("/mine")
def my_teams(ctx: Ctx = Depends(team_user)):
    """The team I belong to / lead, with leader contact, projects and my own open work."""
    ids = list(ctx.db.scalars(select(Team.id).where(or_(Team.leader_id == ctx.user.id, exists().where(TeamMember.team_id == Team.id, TeamMember.user_id == ctx.user.id)))))
    items = []
    for t in ctx.db.scalars(select(Team).where(Team.id.in_(ids)).order_by(Team.name)) if ids else []:
        d = _detail(ctx, t)
        pids = [p["id"] for p in d["projects"]]
        mine = []
        if pids:
            mine = [{"id": x.id, "title": x.title, "project_id": x.project_id, "status": x.status, "due_date": x.due_date, "is_blocked": x.is_blocked}
                    for x in ctx.db.scalars(select(Task).where(Task.project_id.in_(pids), Task.assignee_id == ctx.user.id, Task.status != "done").order_by(Task.due_date.is_(None), Task.due_date))]
        d["my_open_tasks"] = mine
        items.append(d)
    return {"items": items}


@router.get("/available")
def available_people(branch_id: int | None = None, ctx: Ctx = Depends(team_user)):
    """People who may join a team: active, eligible, and not in an *active* team. Branch-scoped for branch staff and leaders."""
    leads = ctx.role == "employee" and ctx.db.scalar(select(Team.id).where(Team.leader_id == ctx.user.id, Team.is_active.is_(True)).limit(1)) is not None
    if ctx.role == "employee" and not leads:
        raise Forbidden()
    busy = exists().where(TeamMember.user_id == User.id, TeamMember.team_id == Team.id, Team.is_active.is_(True))
    stmt = select(User).where(User.is_active.is_(True), User.status != "offboarded", User.role.in_(svc.MEMBER_ROLES), ~busy).order_by(User.full_name)
    if ctx.role in ("manager", "hr", "employee") and ctx.user.branch_id is not None:
        stmt = stmt.where(User.branch_id == ctx.user.branch_id)
    if branch_id is not None:
        stmt = stmt.where(User.branch_id == branch_id)
    return {"items": [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "designation": u.designation,
                       "branch_id": u.branch_id, "avatar_v": u.avatar_name} for u in ctx.db.scalars(stmt)]}


@router.get("/analytics")
def analytics(ctx: Ctx = Depends(require_roles("founder", "hr", "manager"))):
    """Productivity per team: workload, completion, overdue/blocked work, on-time delivery and daily-update compliance."""
    teams = ctx.db.scalars(select(Team).where(_scope(ctx), Team.is_active.is_(True)).order_by(Team.name)).all()
    ids = [t.id for t in teams]
    by_team, _ = _aggregate(_task_rows(ctx, ids))
    counts = _counts(ctx, ids) if ids else {}
    names = _names(ctx, [i for t in teams for i in (t.manager_id, t.leader_id)])
    today = utcnow().date()
    submitted: dict[int, int] = {}
    if ids:
        for tid, n in ctx.db.execute(
                select(TeamMember.team_id, func.count(DailyUpdate.id)).join(DailyUpdate, and_(DailyUpdate.user_id == TeamMember.user_id, DailyUpdate.work_date == today))
                .where(TeamMember.team_id.in_(ids)).group_by(TeamMember.team_id)):
            submitted[tid] = n
    items = []
    for t in teams:
        s = _public_stats(by_team.get(t.id))
        members = counts.get(t.id, (0, 0))[0]
        items.append({
            "team_id": t.id, "name": t.name, "branch_id": t.branch_id, "leader": _person(names.get(t.leader_id)), "manager": _person(names.get(t.manager_id)),
            "members": members, "projects": counts.get(t.id, (0, 0))[1], **s,
            "tasks_per_member": round(s["open_tasks"] / members, 1) if members else 0,
            "completion_rate": round(100 * s["done_count"] / s["task_count"]) if s["task_count"] else 0,
            "updates_today": submitted.get(t.id, 0),
        })
    totals = {k: sum(i[k] for i in items) for k in ("members", "task_count", "done_count", "open_tasks", "overdue_tasks", "blocked_tasks", "done_last_30d")}
    return {"items": items, "totals": totals, "teams": len(items)}


def can_create_teams(ctx: Ctx) -> bool:
    return ctx.role == "founder" or (ctx.role == "manager" and has_permission(ctx.user, "teams.manage"))


def create_team_core(ctx: Ctx, body: TeamCreate) -> Team:
    """Validate and add a team (members, leader, project allocation) to the caller's transaction; the caller commits."""
    _check_name(ctx, body.name)
    if ctx.role == "manager":
        branch_id, manager_id = (ctx.user.branch_id if ctx.user.branch_id is not None else body.branch_id), ctx.user.id
    else:
        branch_id, manager_id = body.branch_id, body.manager_id
    _check_branch_ref(ctx, branch_id)
    _check_manager(ctx, manager_id, branch_id)
    if body.department_id is not None and ctx.db.get(Department, body.department_id) is None:
        raise AppError("Department does not exist")
    member_ids = set(body.member_ids) | ({body.leader_id} if body.leader_id else set())
    people = _people(ctx, member_ids, svc.MEMBER_ROLES, "a team member")
    if body.leader_id:
        _people(ctx, [body.leader_id], svc.LEADER_ROLES, "a team leader")
    _check_branch(ctx, branch_id, people)
    _check_free(ctx, None, member_ids)
    projects = [_assignable_project(ctx, pid) for pid in set(body.project_ids)]
    t = Team(name=body.name.strip(), description=body.description, branch_id=branch_id, department_id=body.department_id,
             manager_id=manager_id, leader_id=body.leader_id, created_by=ctx.user.id)
    ctx.db.add(t)
    ctx.db.flush()
    for p in projects:
        ctx.db.add(TeamProject(team_id=t.id, project_id=p.id, assigned_by=ctx.user.id))
    _join(ctx, t, people)
    if t.leader_id and t.leader_id != ctx.user.id:
        notify(ctx.db, [t.leader_id], "You lead a team", f"You were made team leader of {t.name}.", "team", f"/teams/{t.id}")
    audit(ctx, "team.created", "team", t.id, {"name": t.name, "branch_id": branch_id, "manager_id": manager_id, "leader_id": t.leader_id,
                                              "members": sorted(member_ids), "projects": sorted(p.id for p in projects)})
    emit(ctx.db, "team.created", {"id": t.id, "name": t.name, "leader_id": t.leader_id})
    return t


def allocate_project_core(ctx: Ctx, t: Team, p: Project) -> None:
    """Allocate project `p` to team `t` and give the team access. The caller has checked rights; the caller commits."""
    ctx.db.add(TeamProject(team_id=t.id, project_id=p.id, assigned_by=ctx.user.id))
    ctx.db.flush()
    people = svc.team_member_ids(ctx.db, t.id)
    svc.grant_project_access(ctx.db, [p.id], people)
    notify(ctx.db, [i for i in people if i != ctx.user.id], "Project allocated to your team", f"{p.name} was allocated to team {t.name}.", "team", f"/projects/{p.id}")
    audit(ctx, "team.project_assigned", "team", t.id, {"project_id": p.id, "name": p.name})
    emit(ctx.db, "team.project_assigned", {"team_id": t.id, "project_id": p.id})


@router.post("", status_code=201)
def create_team(body: TeamCreate, ctx: Ctx = Depends(_manager_dep)):
    t = create_team_core(ctx, body)
    ctx.db.commit()
    return _detail(ctx, t)


@router.get("/{team_id}")
def team_detail(team_id: int, ctx: Ctx = Depends(team_user)):
    return _detail(ctx, _get_team(ctx, team_id))


@router.patch("/{team_id}")
def update_team(team_id: int, body: TeamUpdate, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can edit this team")
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        _check_name(ctx, data["name"], exclude=t.id)
        data["name"] = data["name"].strip()
    if "name" in data and data["name"] is None:
        data.pop("name")
    if data.get("is_active") is None:
        data.pop("is_active", None)
    if "department_id" in data and data["department_id"] is not None and ctx.db.get(Department, data["department_id"]) is None:
        raise AppError("Department does not exist")
    if "branch_id" in data and data["branch_id"] != t.branch_id:
        if ctx.role != "founder":
            raise Forbidden("Only a founder can move a team to another branch")
        _check_branch_ref(ctx, data["branch_id"])
        if data["branch_id"] is not None:
            people = list(ctx.db.scalars(select(User).where(User.id.in_(svc.team_member_ids(ctx.db, t.id)))))
            _check_branch(ctx, data["branch_id"], people)
            _check_manager(ctx, t.manager_id, data["branch_id"])
    elif "branch_id" in data:
        data.pop("branch_id")
    for k, v in data.items():
        setattr(t, k, v)
    audit(ctx, "team.updated", "team", t.id, {"fields": sorted(data), **({"is_active": data["is_active"]} if "is_active" in data else {})})
    ctx.db.commit()
    return _detail(ctx, t)


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can delete this team")
    ids = svc.team_member_ids(ctx.db, t.id)
    pids = svc.team_project_ids(ctx.db, t.id)
    name = t.name
    ctx.db.query(TeamMember).filter(TeamMember.team_id == t.id).delete(synchronize_session=False)
    ctx.db.query(TeamProject).filter(TeamProject.team_id == t.id).delete(synchronize_session=False)
    ctx.db.flush()
    svc.revoke_project_access(ctx.db, pids, ids)
    notify(ctx.db, [i for i in ids if i != ctx.user.id], "Team disbanded", f"Team {name} no longer exists.", "team")
    ctx.db.delete(t)
    audit(ctx, "team.deleted", "team", team_id, {"name": name, "members": sorted(ids), "projects": sorted(pids)})
    ctx.db.commit()


# ---- leader, manager, members -------------------------------------------------------------------

@router.put("/{team_id}/leader")
def set_leader(team_id: int, body: LeaderIn, ctx: Ctx = Depends(team_user)):
    """Assign, replace or (with user_id=null) clear the team leader. A new leader joins the team if needed."""
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can assign the leader")
    old = t.leader_id
    if body.user_id == old:
        return _detail(ctx, t)
    if body.user_id is not None:
        [leader] = _people(ctx, [body.user_id], svc.LEADER_ROLES, "a team leader")
        _check_branch(ctx, t.branch_id, [leader])
        if ctx.db.get(TeamMember, (t.id, leader.id)) is None:
            _check_free(ctx, t.id, [leader.id])
            _join(ctx, t, [leader], announce=False)
        t.leader_id = leader.id
        notify(ctx.db, [leader.id], "You lead a team", f"You are now team leader of {t.name}.", "team", f"/teams/{t.id}")
    else:
        t.leader_id = None
    if old and old != t.leader_id:
        notify(ctx.db, [old], "Team leadership changed", f"You are no longer team leader of {t.name}.", "team", f"/teams/{t.id}")
    audit(ctx, "team.leader_changed", "team", t.id, {"from": old, "to": t.leader_id})
    ctx.db.commit()
    return _detail(ctx, t)


@router.post("/{team_id}/reassign")
def reassign_team(team_id: int, body: ReassignIn, ctx: Ctx = Depends(team_user)):
    """Hand the team over to another manager after an organisational change (current manager or founder)."""
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can reassign this team")
    if body.manager_id == t.manager_id:
        return _detail(ctx, t)
    _check_manager(ctx, body.manager_id, t.branch_id)
    old = t.manager_id
    t.manager_id = body.manager_id
    notify(ctx.db, [i for i in (body.manager_id, old) if i and i != ctx.user.id], "Team reassigned",
           f"Management of team {t.name} changed.", "team", f"/teams/{t.id}")
    audit(ctx, "team.reassigned", "team", t.id, {"from": old, "to": body.manager_id})
    ctx.db.commit()
    return _detail(ctx, t)


@router.post("/{team_id}/members")
def add_members(team_id: int, body: MembersIn, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage_members", "You cannot change this team's members")
    if not t.is_active:
        raise AppError("This team is inactive")
    people = _people(ctx, body.user_ids, svc.MEMBER_ROLES, "a team member")
    _check_branch(ctx, t.branch_id, people)
    _check_free(ctx, t.id, [u.id for u in people])
    fresh = [u for u in people if ctx.db.get(TeamMember, (t.id, u.id)) is None]
    _join(ctx, t, fresh)
    audit(ctx, "team.members_added", "team", t.id, {"user_ids": sorted(u.id for u in fresh)})
    ctx.db.commit()
    return _detail(ctx, t)


@router.delete("/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage_members", "You cannot change this team's members")
    if ctx.db.get(TeamMember, (t.id, user_id)) is None:
        raise NotFound("That person is not in this team")
    if user_id == t.leader_id and not _caps(ctx, t)["can_manage"] and ctx.role != "hr":
        raise Forbidden("Only the team's manager can remove the team leader")
    res = svc.release_user(ctx.db, t, user_id)
    notify(ctx.db, [user_id], "Removed from a team", f"You were removed from team {t.name}.", "team")
    if res["was_leader"]:
        notify(ctx.db, [t.manager_id] if t.manager_id and t.manager_id != ctx.user.id else [], "Team has no leader", f"Team {t.name} lost its leader.", "team", f"/teams/{t.id}")
    audit(ctx, "team.member_removed", "team", t.id, {"user_id": user_id, **res})
    ctx.db.commit()
    return {**_detail(ctx, t), "unassigned_tasks": res["unassigned_tasks"]}


@router.post("/transfer")
def transfer(body: TransferIn, ctx: Ctx = Depends(require_roles("hr", "founder"))):
    """Move a person to another team (HR/founder). Moving across branches is founder-only, like any branch assignment."""
    to_team = _get_team(ctx, body.to_team_id)
    u = ctx.db.get(User, body.user_id)
    if u is None or u.role in ("founder", "board_member") or not can_manage_user(ctx, u):
        raise NotFound("Employee not found")
    _people(ctx, [u.id], svc.MEMBER_ROLES, "a team member")
    if not to_team.is_active:
        raise AppError("The destination team is inactive")
    current = svc.team_of(ctx.db, u.id)
    if current is not None and current.id == to_team.id:
        raise AppError("The person is already in that team")
    if current is not None and ctx.db.scalar(select(Team.id).where(Team.id == current.id, _scope(ctx))) is None:
        raise NotFound("Employee not found")
    branch_changed = to_team.branch_id is not None and u.branch_id != to_team.branch_id
    if branch_changed and ctx.role != "founder":
        raise Forbidden("Only a founder can move people between branches")
    freed = 0
    if current is not None:
        res = svc.release_user(ctx.db, current, u.id)
        freed = res["unassigned_tasks"]
    released: list[int] = []
    if branch_changed:
        b = ctx.db.get(Branch, to_team.branch_id)
        u.branch_id = b.id
        u.location = b.city or u.location
        ctx.db.flush()
        released = _release_cross_branch_lines(ctx, u)
        svc.release_if_branch_mismatch(ctx.db, u)
    _join(ctx, to_team, [u], announce=False)
    notify(ctx.db, [u.id], "Team transfer", f"You were moved to team {to_team.name}." + (f" {body.note}" if body.note else ""), "team", f"/teams/{to_team.id}")
    notify(ctx.db, [i for i in {to_team.leader_id, to_team.manager_id, current.leader_id if current else None, current.manager_id if current else None} if i and i not in (ctx.user.id, u.id)],
           "Team transfer", f"{u.full_name} moved from {current.name if current else 'no team'} to {to_team.name}.", "team", f"/teams/{to_team.id}")
    audit(ctx, "team.member_transferred", "team", to_team.id, {
        "user_id": u.id, "from_team": current.id if current else None, "to_team": to_team.id, "branch_changed": branch_changed,
        "unassigned_tasks": freed, "released_reporting_lines": sorted(set(released)), "note": body.note})
    ctx.db.commit()
    return {"user_id": u.id, "from_team_id": current.id if current else None, "to_team_id": to_team.id,
            "branch_changed": branch_changed, "unassigned_tasks": freed}


# ---- projects ---------------------------------------------------------------------------------------

def _assignable_project(ctx: Ctx, project_id: int) -> Project:
    """A project the caller may allocate: its owner, or a founder."""
    p = get_project(ctx, project_id)
    if ctx.role != "founder" and p.owner_id != ctx.user.id:
        raise Forbidden("You can only allocate projects you own")
    return p


@router.post("/{team_id}/projects", status_code=201)
def assign_project(team_id: int, body: ProjectIn, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can allocate projects")
    if not t.is_active:
        raise AppError("This team is inactive")
    p = _assignable_project(ctx, body.project_id)
    if ctx.db.get(TeamProject, (t.id, p.id)) is not None:
        raise Conflict("This project is already allocated to the team")
    allocate_project_core(ctx, t, p)
    ctx.db.commit()
    return _detail(ctx, t)


@router.delete("/{team_id}/projects/{project_id}")
def unassign_project(team_id: int, project_id: int, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_manage", "Only the team's manager or a founder can change project allocation")
    link = ctx.db.get(TeamProject, (t.id, project_id))
    if link is None:
        raise NotFound("That project is not allocated to this team")
    p = ctx.db.get(Project, project_id)
    ctx.db.delete(link)
    ctx.db.flush()
    members = svc.team_member_ids(ctx.db, t.id)
    svc.revoke_project_access(ctx.db, [project_id], members)
    notify(ctx.db, [i for i in members if i != ctx.user.id], "Project removed from your team", f"{p.name if p else 'A project'} is no longer allocated to team {t.name}.", "team")
    audit(ctx, "team.project_unassigned", "team", t.id, {"project_id": project_id})
    ctx.db.commit()
    return _detail(ctx, t)


# ---- daily updates & reports ----------------------------------------------------------------------

@router.get("/{team_id}/updates")
def team_updates(team_id: int, work_date: date | None = None, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_monitor", "Only the team's leader, manager or HR can see daily updates")
    day = work_date or utcnow().date()
    ids = svc.team_member_ids(ctx.db, t.id)
    names = _names(ctx, ids)
    ups = {u.user_id: u for u in ctx.db.scalars(select(DailyUpdate).where(DailyUpdate.user_id.in_(ids), DailyUpdate.work_date == day))} if ids else {}
    items = [{"user_id": i, "full_name": names[i].full_name, "submitted": i in ups, "update": ser_update(ups[i], names[i].full_name) if i in ups else None}
             for i in sorted(ids, key=lambda x: names[x].full_name) if i in names]
    return {"work_date": day, "submitted": sum(1 for x in items if x["submitted"]), "missing": sum(1 for x in items if not x["submitted"]), "items": items}


@router.post("/{team_id}/updates/{update_id}/review")
def review_update(team_id: int, update_id: int, body: UpdateReviewIn, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    c = _caps(ctx, t)
    if not (c["can_lead"] or c["can_manage"]):
        raise Forbidden("Only the team's leader or manager can review daily updates")
    row = ctx.db.get(DailyUpdate, update_id)
    if row is None or ctx.db.get(TeamMember, (t.id, row.user_id)) is None:
        raise NotFound("Update not found in this team")
    if row.user_id == ctx.user.id:
        raise Forbidden("You cannot review your own update")
    row.review_status, row.review_comment, row.reviewed_by, row.reviewed_at = body.status, body.comment, ctx.user.id, utcnow()
    notify(ctx.db, [row.user_id], "Daily update " + ("reviewed" if body.status == "reviewed" else "needs changes"), body.comment or str(row.work_date), "daily_update", "/updates")
    audit(ctx, "daily_update.reviewed", "daily_update", row.id, {"status": body.status, "team_id": t.id})
    ctx.db.commit()
    return ser_update(row, ctx.db.get(User, row.user_id).full_name)


def _ser_report(r: TeamReport, names: dict) -> dict:
    return {"id": r.id, "team_id": r.team_id, "author_id": r.author_id, "author_name": names[r.author_id].full_name if r.author_id in names else None,
            "project_id": r.project_id, "health": r.health, "summary": r.summary, "created_at": r.created_at}


@router.post("/{team_id}/reports", status_code=201)
def submit_report(team_id: int, body: ReportIn, ctx: Ctx = Depends(team_user)):
    """Team leader -> manager progress report."""
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_lead", "Only the team leader can submit progress reports")
    if body.project_id is not None and ctx.db.get(TeamProject, (t.id, body.project_id)) is None:
        raise AppError("That project is not allocated to this team")
    r = TeamReport(team_id=t.id, author_id=ctx.user.id, project_id=body.project_id, health=body.health, summary=body.summary.strip())
    ctx.db.add(r)
    ctx.db.flush()
    notify(ctx.db, [i for i in (t.manager_id,) if i and i != ctx.user.id], f"Team report: {t.name} ({body.health.replace('_', ' ')})", body.summary[:200], "team", f"/teams/{t.id}")
    audit(ctx, "team.report_submitted", "team", t.id, {"report_id": r.id, "health": r.health})
    ctx.db.commit()
    return _ser_report(r, {ctx.user.id: ctx.user})


@router.get("/{team_id}/reports")
def list_reports(team_id: int, ctx: Ctx = Depends(team_user)):
    t = _get_team(ctx, team_id)
    _need(ctx, t, "can_monitor", "Only the team's leader, manager or HR can read reports")
    rows = ctx.db.scalars(select(TeamReport).where(TeamReport.team_id == t.id).order_by(TeamReport.id.desc()).limit(50)).all()
    names = _names(ctx, [r.author_id for r in rows])
    return {"items": [_ser_report(r, names) for r in rows]}
