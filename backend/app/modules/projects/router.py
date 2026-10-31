from datetime import date

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import and_, exists, false, func, or_, select, true

from app import storage
from app.access import has_permission, require_permission, same_branch
from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import Attachment, Milestone, Project, ProjectMember, Task, TaskComment, TaskDependency, User
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import live_event, notify
from app.modules.projects.schemas import (
    CommentIn, DependenciesIn, MembersIn, MilestoneIn, MilestoneUpdate, ProjectCreate, ProjectUpdate, TaskCreate, TaskReview, TaskUpdate,
)
from app.modules.teams.service import assignable_ids, leaders_for_task, leads_project
from app.modules.webhooks.service import emit

router = APIRouter(tags=["projects"])


def project_manager(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if ctx.role in ("founder", "hr"):
        return ctx
    if ctx.role == "manager":
        if not has_permission(ctx.user, "projects.manage"):
            raise Forbidden("Your account does not have the 'projects.manage' permission")
        return ctx
    raise Forbidden()


manager_only = project_manager


# ---- access ---------------------------------------------------------------------------------

def _member_ids(ctx: Ctx, project_id: int) -> list[int]:
    return list(ctx.db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)))


def _visible(ctx: Ctx):
    if ctx.role == "founder" or (ctx.role == "hr" and ctx.user.branch_id is None):
        return True
    if ctx.role == "hr":  # branch HR: projects owned by people of their branch
        return Project.owner_id.in_(select(User.id).where(User.branch_id == ctx.user.branch_id))
    me = ctx.user.id
    # "company" projects are readable (never writable) by everyone in the owner's branch scope; "restricted" ones only by their people
    shared = and_(Project.visibility == "company", true() if ctx.user.branch_id is None else
                  Project.owner_id.in_(select(User.id).where(or_(User.branch_id == ctx.user.branch_id, User.branch_id.is_(None)))))
    if ctx.role == "board_member":
        shared = false()
    return or_(
        shared,
        Project.owner_id == me,
        Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == me)),
        Project.id.in_(select(Task.project_id).where(Task.assignee_id == me)),
    )


def get_project(ctx: Ctx, project_id: int, *, write: bool = False) -> Project:
    p = ctx.db.scalar(select(Project).where(Project.id == project_id, _visible(ctx)))
    if p is None:
        raise NotFound("Project not found")
    if write and p.owner_id != ctx.user.id and ctx.role not in ("founder", "hr"):
        raise Forbidden("Only the project owner can change this project")
    return p


def get_task(ctx: Ctx, task_id: int) -> tuple[Task, Project]:
    t = ctx.db.get(Task, task_id)
    if t is None:
        raise NotFound("Task not found")
    return t, get_project(ctx, t.project_id)  # raises NotFound if the project isn't visible


def _check_users(ctx: Ctx, ids: list[int]) -> None:
    if not ids:
        return
    people = list(ctx.db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))))
    if len(people) != len(set(ids)):
        raise AppError("One or more users do not exist or are inactive")
    if any(not same_branch(ctx.user, u) for u in people):
        raise AppError("You can only involve people from your own branch")


def _writer(ctx: Ctx, p: Project) -> bool:
    """Founder/HR, or the project's owner (a manager holding `projects.manage`)."""
    if ctx.role in ("founder", "hr"):
        return True
    return ctx.role == "manager" and has_permission(ctx.user, "projects.manage") and p.owner_id == ctx.user.id


def _task_project(ctx: Ctx, project_id: int) -> tuple[Project, bool]:
    """Project the caller may add tasks to, and whether they do so only as a team leader (limited to their team)."""
    p = get_project(ctx, project_id)
    if _writer(ctx, p):
        return p, False
    if leads_project(ctx.db, ctx.user.id, p.id):
        return p, True
    if ctx.role == "manager" and not has_permission(ctx.user, "projects.manage"):
        raise Forbidden("Your account does not have the 'projects.manage' permission")
    raise Forbidden("Only the project owner or a team leader of this project can create tasks")


def _leader_assignee(ctx: Ctx, p: Project, user_id: int) -> None:
    if user_id not in assignable_ids(ctx.db, ctx.user.id, p.id):
        raise Forbidden("Team leaders can only assign tasks to members of their own team")


# ---- serializers ----------------------------------------------------------------------------

def ser_task(t: Task, deps: list[int] | None = None) -> dict:
    overdue = bool(t.due_date and t.due_date < utcnow().date() and t.status != "done")
    return {
        "id": t.id, "project_id": t.project_id, "milestone_id": t.milestone_id, "title": t.title, "description": t.description,
        "status": t.status, "priority": t.priority, "assignee_id": t.assignee_id, "created_by": t.created_by,
        "due_date": t.due_date, "progress": t.progress, "approved_by": t.approved_by, "approved_at": t.approved_at,
        "task_type": t.task_type, "labels": t.labels or [], "start_date": t.start_date, "estimated_hours": t.estimated_hours,
        "actual_hours": t.actual_hours, "review_notes": t.review_notes, "completed_on": t.completed_on,
        "overdue": overdue, "is_blocked": t.is_blocked, "blocker_note": t.blocker_note, "depends_on": deps or [], "created_at": t.created_at, "updated_at": t.updated_at,
    }


def _deps_map(ctx: Ctx, task_ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    if task_ids:
        for tid, dep in ctx.db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_id).where(TaskDependency.task_id.in_(task_ids))):
            out.setdefault(tid, []).append(dep)
    return out


def _progress(ctx: Ctx, project_id: int) -> dict:
    rows = ctx.db.execute(select(Task.status, func.count(Task.id), func.coalesce(func.sum(Task.progress), 0)).where(Task.project_id == project_id).group_by(Task.status)).all()
    total = sum(r[1] for r in rows)
    done = sum(r[1] for r in rows if r[0] == "done")
    pct = round(sum(r[2] for r in rows) / total) if total else 0
    return {"task_count": total, "done_count": done, "progress": pct}


def ser_project(ctx: Ctx, p: Project, detail: bool = False) -> dict:
    hours = ctx.db.execute(select(func.coalesce(func.sum(Task.estimated_hours), 0), func.coalesce(func.sum(Task.actual_hours), 0)).where(Task.project_id == p.id)).one()
    d = {
        "code": p.code, "category": p.category, "client_name": p.client_name, "risk_level": p.risk_level, "visibility": p.visibility,
        "estimated_hours": p.estimated_hours, "tags": p.tags or [], "completed_on": p.completed_on,
        "task_estimated_hours": float(hours[0]), "task_actual_hours": float(hours[1]),
        "id": p.id, "name": p.name, "description": p.description, "status": p.status, "owner_id": p.owner_id,
        "start_date": p.start_date, "due_date": p.due_date, "created_at": p.created_at, **_progress(ctx, p.id),
        "can_edit": p.owner_id == ctx.user.id or ctx.role in ("founder", "hr"),
    }
    d["can_assign_tasks"] = d["can_edit"] or leads_project(ctx.db, ctx.user.id, p.id)
    if detail:
        if not d["can_edit"] and d["can_assign_tasks"]:
            d["assignable_ids"] = sorted(assignable_ids(ctx.db, ctx.user.id, p.id))
        d["member_ids"] = _member_ids(ctx, p.id)
        d["milestones"] = [
            {"id": m.id, "title": m.title, "due_date": m.due_date, "completed": m.completed}
            for m in ctx.db.scalars(select(Milestone).where(Milestone.project_id == p.id).order_by(Milestone.due_date, Milestone.id))
        ]
    return d


# ---- projects -------------------------------------------------------------------------------

@router.get("/projects")
def list_projects(q: str | None = None, status: str | None = None, risk_level: str | None = None, category: str | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Project).where(_visible(ctx)).order_by(Project.id.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Project.name).like(like), func.lower(Project.code).like(like)))
    if status:
        stmt = stmt.where(Project.status == status)
    if risk_level:
        stmt = stmt.where(Project.risk_level == risk_level)
    if category:
        stmt = stmt.where(func.lower(Project.category) == category.lower())
    return paginate(ctx.db, stmt, params, lambda p: ser_project(ctx, p))


def _unique_code(ctx: Ctx, code: str | None, exclude: int | None = None) -> None:
    if code:
        stmt = select(Project.id).where(func.lower(Project.code) == code.lower())
        if exclude:
            stmt = stmt.where(Project.id != exclude)
        if ctx.db.scalar(stmt):
            raise Conflict("A project with this code already exists")


def _project_team(ctx: Ctx, p: Project, body: ProjectCreate):
    """Optional team for a new project, created/allocated in the same transaction (any failure rolls the project back too)."""
    if body.team_id is None and body.team is None:
        return None
    from app.modules.teams import router as teams  # late import: the teams module builds on this one
    if body.team_id is not None and body.team is not None:
        raise AppError("Choose an existing team or create a new one, not both")
    if body.team_id is not None:
        t = teams._get_team(ctx, body.team_id)
        teams._need(ctx, t, "can_manage", "Only the team's manager or a founder can allocate projects to it")
        if not t.is_active:
            raise AppError("This team is inactive")
        teams.allocate_project_core(ctx, t, p)
        return t
    if not teams.can_create_teams(ctx):
        raise Forbidden("Only a founder or a manager with the 'teams.manage' permission can create a project team")
    from app.modules.teams.schemas import TeamCreate
    t = teams.create_team_core(ctx, TeamCreate(
        name=body.team.name or f"{p.name} Team", leader_id=body.team.leader_id, member_ids=body.team.member_ids, project_ids=[p.id]))
    return t


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, ctx: Ctx = Depends(manager_only)):
    if ctx.role == "founder":
        raise Forbidden("founder cannot create")
    _check_users(ctx, body.member_ids)
    _unique_code(ctx, body.code)
    p = Project(name=body.name, description=body.description, status=body.status, owner_id=ctx.user.id,
                start_date=body.start_date, due_date=body.due_date, code=body.code, category=body.category, client_name=body.client_name,
                risk_level=body.risk_level, visibility=body.visibility, estimated_hours=body.estimated_hours, tags=body.tags,
                completed_on=utcnow().date() if body.status == "completed" else None)
    ctx.db.add(p)
    ctx.db.flush()
    if not p.code:
        p.code = f"PRJ-{p.id:04d}"
    for uid in set(body.member_ids) | {ctx.user.id}:
        ctx.db.add(ProjectMember(project_id=p.id, user_id=uid))
    notify(ctx.db, [u for u in body.member_ids if u != ctx.user.id], "Added to project", p.name, "project", f"/projects/{p.id}")
    team = _project_team(ctx, p, body)
    audit(ctx, "project.created", "project", p.id, {"team_id": team.id} if team else None)
    emit(ctx.db, "project.created", {"id": p.id, "name": p.name, "owner_id": p.owner_id})
    ctx.db.commit()
    return ser_project(ctx, p, detail=True)


@router.get("/projects/{project_id}")
def project_detail(project_id: int, ctx: Ctx = Depends(get_ctx)):
    return ser_project(ctx, get_project(ctx, project_id), detail=True)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, ctx: Ctx = Depends(manager_only)):
    p = get_project(ctx, project_id, write=True)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "status", "risk_level", "visibility", "code") and v is None)}
    _unique_code(ctx, data.get("code"), exclude=p.id)
    old_status = p.status
    for k, v in data.items():
        setattr(p, k, v)
    if p.start_date and p.due_date and p.due_date < p.start_date:
        raise AppError("due_date cannot be before start_date")
    if p.status == "completed" and old_status != "completed":
        p.completed_on = utcnow().date()
    elif p.status != "completed":
        p.completed_on = None
    audit(ctx, "project.updated", "project", p.id, {"fields": sorted(data)})
    ctx.db.commit()
    return ser_project(ctx, p, detail=True)


@router.put("/projects/{project_id}/members")
def set_members(project_id: int, body: MembersIn, ctx: Ctx = Depends(manager_only)):
    p = get_project(ctx, project_id, write=True)
    ids = set(body.member_ids) | {p.owner_id}
    _check_users(ctx, list(ids))
    current = set(_member_ids(ctx, p.id))
    for uid in current - ids:
        if ctx.db.scalar(select(func.count(Task.id)).where(Task.project_id == p.id, Task.assignee_id == uid, Task.status != "done")):
            raise AppError("Cannot remove a member who still has open tasks in this project")
        ctx.db.delete(ctx.db.get(ProjectMember, (p.id, uid)))
    for uid in ids - current:
        ctx.db.add(ProjectMember(project_id=p.id, user_id=uid))
    notify(ctx.db, list(ids - current - {ctx.user.id}), "Added to project", p.name, "project", f"/projects/{p.id}")
    audit(ctx, "project.members_changed", "project", p.id)
    ctx.db.commit()
    return ser_project(ctx, p, detail=True)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, ctx: Ctx = Depends(manager_only)):
    p = get_project(ctx, project_id, write=True)
    task_ids = list(ctx.db.scalars(select(Task.id).where(Task.project_id == p.id)))
    files = list(ctx.db.scalars(select(Attachment.stored_name).where(Attachment.entity_type == "task", Attachment.entity_id.in_(task_ids)))) if task_ids else []
    if task_ids:
        ctx.db.query(Attachment).filter(Attachment.entity_type == "task", Attachment.entity_id.in_(task_ids)).delete(synchronize_session=False)
    ctx.db.delete(p)
    audit(ctx, "project.deleted", "project", project_id, {"name": p.name})
    ctx.db.commit()
    for f in files:
        storage.delete_file(ctx.company_id, f)


# ---- milestones -----------------------------------------------------------------------------

@router.post("/projects/{project_id}/milestones", status_code=201)
def add_milestone(project_id: int, body: MilestoneIn, ctx: Ctx = Depends(manager_only)):
    p = get_project(ctx, project_id, write=True)
    m = Milestone(project_id=p.id, title=body.title, due_date=body.due_date)
    ctx.db.add(m)
    ctx.db.commit()
    return {"id": m.id, "title": m.title, "due_date": m.due_date, "completed": m.completed}


def _milestone(ctx: Ctx, mid: int) -> Milestone:
    m = ctx.db.get(Milestone, mid)
    if m is None:
        raise NotFound()
    get_project(ctx, m.project_id, write=True)
    return m


@router.patch("/milestones/{mid}")
def update_milestone(mid: int, body: MilestoneUpdate, ctx: Ctx = Depends(manager_only)):
    m = _milestone(ctx, mid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    ctx.db.commit()
    return {"id": m.id, "title": m.title, "due_date": m.due_date, "completed": m.completed}


@router.delete("/milestones/{mid}", status_code=204)
def delete_milestone(mid: int, ctx: Ctx = Depends(manager_only)):
    ctx.db.delete(_milestone(ctx, mid))
    ctx.db.commit()


# ---- tasks ----------------------------------------------------------------------------------

def _validate_milestone(ctx: Ctx, project_id: int, milestone_id: int | None) -> None:
    if milestone_id is not None:
        m = ctx.db.get(Milestone, milestone_id)
        if m is None or m.project_id != project_id:
            raise AppError("Milestone does not belong to this project")


def _ensure_member(ctx: Ctx, project_id: int, user_id: int) -> None:
    _check_users(ctx, [user_id])
    if ctx.db.get(ProjectMember, (project_id, user_id)) is None:
        ctx.db.add(ProjectMember(project_id=project_id, user_id=user_id))


@router.get("/projects/{project_id}/tasks")
def project_tasks(project_id: int, status: str | None = None, assignee_id: int | None = None, task_type: str | None = None, ctx: Ctx = Depends(get_ctx)):
    p = get_project(ctx, project_id)
    stmt = select(Task).where(Task.project_id == p.id).order_by(Task.id)
    if status:
        stmt = stmt.where(Task.status == status)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    tasks = ctx.db.scalars(stmt).all()
    deps = _deps_map(ctx, [t.id for t in tasks])
    return {"items": [ser_task(t, deps.get(t.id)) for t in tasks]}


@router.get("/tasks/mine")
def my_tasks(status: str | None = None, scope: str | None = None, assignee_id: int | None = None, project_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    if scope in ("all", "team") and ctx.role in ("founder", "manager", "hr"):
        stmt = select(Task).join(Project, Project.id == Task.project_id).where(_visible(ctx))
        if assignee_id:
            stmt = stmt.where(Task.assignee_id == assignee_id)
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
    else:
        stmt = select(Task).where(Task.assignee_id == ctx.user.id)
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date, Task.id.desc())
    tasks = ctx.db.scalars(stmt).all()
    deps = _deps_map(ctx, [t.id for t in tasks])
    return {"items": [ser_task(t, deps.get(t.id)) for t in tasks]}


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task(project_id: int, body: TaskCreate, ctx: Ctx = Depends(get_ctx)):
    p, lead_only = _task_project(ctx, project_id)
    _validate_milestone(ctx, p.id, body.milestone_id)
    if body.assignee_id:
        if lead_only:
            _leader_assignee(ctx, p, body.assignee_id)
        _ensure_member(ctx, p.id, body.assignee_id)
    t = Task(project_id=p.id, title=body.title, description=body.description, priority=body.priority,
             assignee_id=body.assignee_id, milestone_id=body.milestone_id, due_date=body.due_date, created_by=ctx.user.id,
             task_type=body.task_type, labels=body.labels, start_date=body.start_date, estimated_hours=body.estimated_hours, actual_hours=body.actual_hours)
    ctx.db.add(t)
    ctx.db.flush()
    if t.assignee_id and t.assignee_id != ctx.user.id:
        notify(ctx.db, [t.assignee_id], "New task assigned", t.title, "task", f"/tasks/{t.id}")
    audit(ctx, "task.created", "task", t.id)
    emit(ctx.db, "task.created", {"id": t.id, "project_id": p.id, "title": t.title, "assignee_id": t.assignee_id})
    live_event(ctx.db, _member_ids(ctx, p.id), "task.created", {"task_id": t.id, "project_id": p.id})
    ctx.db.commit()
    return ser_task(t)


@router.get("/tasks/{task_id}")
def task_detail(task_id: int, ctx: Ctx = Depends(get_ctx)):
    t, _ = get_task(ctx, task_id)
    return ser_task(t, _deps_map(ctx, [t.id]).get(t.id))


def _unfinished_deps(ctx: Ctx, task_id: int) -> list[int]:
    return list(ctx.db.scalars(
        select(Task.id).join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .where(TaskDependency.task_id == task_id, Task.status != "done")
    ))


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, ctx: Ctx = Depends(get_ctx)):
    t, p = get_task(ctx, task_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("is_blocked", "task_type"):
        if data.get(k) is None:
            data.pop(k, None)
    if data.get("status") == "changes_requested":
        raise AppError("Use the review action to request changes, with a comment")
    is_owner = p.owner_id == ctx.user.id or ctx.role in ("founder", "hr")
    is_assignee = t.assignee_id == ctx.user.id
    is_lead = not is_owner and leads_project(ctx.db, ctx.user.id, p.id)
    if not (is_owner or is_assignee or is_lead):
        raise Forbidden()
    if not (is_owner or is_lead):
        if set(data) - {"status", "progress", "is_blocked", "blocker_note", "actual_hours"}:
            raise Forbidden("Assignees can only update status, progress, blockers and logged hours")
    if not is_owner and data.get("status") == "done":
        raise Forbidden("Submit the task for review; your manager approves completion")
    if is_lead and not is_assignee and t.assignee_id is not None and t.assignee_id not in assignable_ids(ctx.db, ctx.user.id, p.id):
        raise Forbidden("This task is assigned to someone outside your team")
    old_status, old_blocked = t.status, t.is_blocked
    if "milestone_id" in data:
        _validate_milestone(ctx, p.id, data["milestone_id"])
    if data.get("assignee_id"):
        if is_lead:
            _leader_assignee(ctx, p, data["assignee_id"])
        _ensure_member(ctx, p.id, data["assignee_id"])
    start, due = data.get("start_date", t.start_date), data.get("due_date", t.due_date)
    if start and due and due < start:
        raise AppError("due_date cannot be before start_date")
    new_status = data.get("status")
    if new_status and new_status != old_status and new_status in ("in_progress", "review", "done"):
        blocked = _unfinished_deps(ctx, t.id)
        if blocked:
            raise AppError(f"Blocked by unfinished dependencies: {blocked}", code="blocked_by_dependency")
    for k, v in data.items():
        setattr(t, k, v)
    if "is_blocked" in data:
        if not t.is_blocked:
            t.blocker_note = None
        elif not old_blocked:
            notify(ctx.db, sorted(({p.owner_id} | set(leaders_for_task(ctx.db, p.id, t.assignee_id))) - {ctx.user.id}),
                   "Task blocked", f"{t.title}" + (f": {t.blocker_note}" if t.blocker_note else ""), "task", f"/tasks/{t.id}")
    if new_status == "done":
        t.is_blocked, t.blocker_note = False, None
        t.progress, t.approved_by, t.approved_at = 100, ctx.user.id, utcnow()
        t.completed_on = utcnow().date()
    elif new_status and old_status == "done":
        t.approved_by = t.approved_at = t.completed_on = None
    if new_status == "review" and old_status != "review":
        t.progress = max(t.progress, 90)
        notify(ctx.db, sorted({p.owner_id, *leaders_for_task(ctx.db, p.id, t.assignee_id)} - {ctx.user.id}), "Task ready for review", t.title, "task", f"/tasks/{t.id}")
    if "assignee_id" in data and t.assignee_id and t.assignee_id != ctx.user.id:
        notify(ctx.db, [t.assignee_id], "Task assigned to you", t.title, "task", f"/tasks/{t.id}")
    audit(ctx, "task.updated", "task", t.id, {"fields": sorted(data)})
    emit(ctx.db, "task.updated", {"id": t.id, "project_id": p.id, "status": t.status, "progress": t.progress})
    live_event(ctx.db, _member_ids(ctx, p.id), "task.updated", {"task_id": t.id, "project_id": p.id, "status": t.status})
    ctx.db.commit()
    return ser_task(t, _deps_map(ctx, [t.id]).get(t.id))


@router.post("/tasks/{task_id}/review")
def review_task(task_id: int, body: TaskReview, ctx: Ctx = Depends(manager_only)):
    t, p = get_task(ctx, task_id)
    if p.owner_id != ctx.user.id and ctx.role not in ("founder", "hr"):
        raise Forbidden("Only the project owner can review tasks")
    if t.status != "review":
        raise AppError("Task is not awaiting review")
    if body.approved:
        t.status, t.progress, t.approved_by, t.approved_at = "done", 100, ctx.user.id, utcnow()
        t.completed_on = utcnow().date()
        t.review_notes = body.note.strip() if body.note and body.note.strip() else t.review_notes
        emit(ctx.db, "task.approved", {"id": t.id, "project_id": p.id})
    else:
        t.status, t.progress, t.review_notes = "changes_requested", min(t.progress, 80), body.note.strip()
    if t.assignee_id:
        notify(ctx.db, [t.assignee_id], "Task approved" if body.approved else "Task needs changes", body.note or t.title, "task", f"/tasks/{t.id}")
    audit(ctx, "task.reviewed", "task", t.id, {"approved": body.approved})
    live_event(ctx.db, _member_ids(ctx, p.id), "task.updated", {"task_id": t.id, "project_id": p.id, "status": t.status})
    ctx.db.commit()
    return ser_task(t)


@router.put("/tasks/{task_id}/dependencies")
def set_dependencies(task_id: int, body: DependenciesIn, ctx: Ctx = Depends(manager_only)):
    t, p = get_task(ctx, task_id)
    if p.owner_id != ctx.user.id and ctx.role not in ("founder", "hr"):
        raise Forbidden()
    ids = set(body.depends_on)
    if t.id in ids:
        raise AppError("A task cannot depend on itself")
    if ids:
        valid = set(ctx.db.scalars(select(Task.id).where(Task.id.in_(ids), Task.project_id == p.id)))
        if valid != ids:
            raise AppError("Dependencies must be tasks in the same project")
    # cycle check: walking from each dependency must never reach this task
    edges: dict[int, list[int]] = {}
    for a, b in ctx.db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_id).join(Task, Task.id == TaskDependency.task_id).where(Task.project_id == p.id)):
        edges.setdefault(a, []).append(b)
    edges[t.id] = list(ids)
    stack, seen = list(ids), set()
    while stack:
        cur = stack.pop()
        if cur == t.id:
            raise AppError("Dependency would create a cycle")
        if cur not in seen:
            seen.add(cur)
            stack.extend(edges.get(cur, []))
    ctx.db.query(TaskDependency).filter(TaskDependency.task_id == t.id).delete()
    for d in ids:
        ctx.db.add(TaskDependency(task_id=t.id, depends_on_id=d))
    ctx.db.commit()
    return ser_task(t, sorted(ids))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, ctx: Ctx = Depends(manager_only)):
    t, p = get_task(ctx, task_id)
    if p.owner_id != ctx.user.id and ctx.role not in ("founder", "hr"):
        raise Forbidden()
    files = list(ctx.db.scalars(select(Attachment.stored_name).where(Attachment.entity_type == "task", Attachment.entity_id == t.id)))
    ctx.db.query(Attachment).filter(Attachment.entity_type == "task", Attachment.entity_id == t.id).delete()
    ctx.db.delete(t)
    audit(ctx, "task.deleted", "task", task_id)
    ctx.db.commit()
    for f in files:
        storage.delete_file(ctx.company_id, f)


# ---- attachments ----------------------------------------------------------------------------

def _ser_comment(c: TaskComment, names: dict[int, str]) -> dict:
    return {"id": c.id, "task_id": c.task_id, "author_id": c.author_id, "author": names.get(c.author_id, "Former member"), "body": c.body, "created_at": c.created_at}


def _can_comment(ctx: Ctx, t: Task, p: Project) -> bool:
    return (ctx.role in ("founder", "hr") or p.owner_id == ctx.user.id or t.assignee_id == ctx.user.id
            or ctx.user.id in _member_ids(ctx, p.id))


@router.get("/tasks/{task_id}/comments")
def list_comments(task_id: int, ctx: Ctx = Depends(get_ctx)):
    t, p = get_task(ctx, task_id)  # anyone who can see the task can read its discussion
    rows = list(ctx.db.scalars(select(TaskComment).where(TaskComment.task_id == t.id).order_by(TaskComment.id)))
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User).where(User.id.in_({c.author_id for c in rows if c.author_id})))} if rows else {}
    return {"items": [_ser_comment(c, names) for c in rows], "can_comment": _can_comment(ctx, t, p)}


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment(task_id: int, body: CommentIn, ctx: Ctx = Depends(get_ctx)):
    t, p = get_task(ctx, task_id)
    if not _can_comment(ctx, t, p):
        raise Forbidden("Only the project owner, its members and the assignee can comment on this task")
    c = TaskComment(task_id=t.id, author_id=ctx.user.id, body=body.body)
    ctx.db.add(c)
    ctx.db.flush()
    audience = {p.owner_id, t.assignee_id} - {None, ctx.user.id}
    if audience:
        notify(ctx.db, sorted(audience), "New comment on a task", f"{ctx.user.full_name} on \"{t.title}\": {body.body[:120]}", "task", "/my-tasks")
    ctx.db.commit()
    return _ser_comment(c, {ctx.user.id: ctx.user.full_name})


@router.delete("/tasks/{task_id}/comments/{comment_id}", status_code=204)
def delete_comment(task_id: int, comment_id: int, ctx: Ctx = Depends(get_ctx)):
    t, p = get_task(ctx, task_id)
    c = ctx.db.get(TaskComment, comment_id)
    if c is None or c.task_id != t.id:
        raise NotFound("Comment not found")
    if not (c.author_id == ctx.user.id or p.owner_id == ctx.user.id or ctx.role == "founder"):
        raise Forbidden("You can delete your own comments; the project owner and founders can delete any")
    ctx.db.delete(c)
    ctx.db.commit()


@router.post("/tasks/{task_id}/attachments", status_code=201)
async def add_attachment(task_id: int, file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    t, p = get_task(ctx, task_id)
    if not (p.owner_id == ctx.user.id or t.assignee_id == ctx.user.id or ctx.role in ("founder", "hr")):
        raise Forbidden()
    name, stored, size = await storage.save_upload(ctx.company_id, file)
    a = Attachment(entity_type="task", entity_id=t.id, filename=name, stored_name=stored, size=size, uploaded_by=ctx.user.id)
    ctx.db.add(a)
    ctx.db.commit()
    return {"id": a.id, "filename": a.filename, "size": a.size, "created_at": a.created_at}


@router.get("/tasks/{task_id}/attachments")
def list_attachments(task_id: int, ctx: Ctx = Depends(get_ctx)):
    t, _ = get_task(ctx, task_id)
    rows = ctx.db.scalars(select(Attachment).where(Attachment.entity_type == "task", Attachment.entity_id == t.id).order_by(Attachment.id))
    return {"items": [{"id": a.id, "filename": a.filename, "size": a.size, "uploaded_by": a.uploaded_by, "created_at": a.created_at} for a in rows]}


def _attachment(ctx: Ctx, aid: int) -> Attachment:
    a = ctx.db.get(Attachment, aid)
    if a is None or a.entity_type != "task":
        raise NotFound()
    get_task(ctx, a.entity_id)  # enforces project visibility
    return a


@router.get("/attachments/{aid}/download")
def download_attachment(aid: int, ctx: Ctx = Depends(get_ctx)):
    a = _attachment(ctx, aid)
    return FileResponse(storage.path_for(ctx.company_id, a.stored_name), filename=a.filename, headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{aid}", status_code=204)
def delete_attachment(aid: int, ctx: Ctx = Depends(get_ctx)):
    a = _attachment(ctx, aid)
    _, p = get_task(ctx, a.entity_id)
    if not (a.uploaded_by == ctx.user.id or p.owner_id == ctx.user.id):
        raise Forbidden()
    stored = a.stored_name
    ctx.db.delete(a)
    ctx.db.commit()
    storage.delete_file(ctx.company_id, stored)
