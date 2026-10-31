"""Team domain helpers shared by the teams, projects, updates, employees and organisation modules.

Rules encoded here:
- A person belongs to at most one team; the team's leader is always a member.
- Only employees, managers and HR can be members; only employees and managers can lead.
- A team that has a branch only accepts people of that branch.
- Everyone on a team (and its leader) is a project member of every project allocated to the team, so the existing
  project/task visibility rules apply to team work without special cases.
"""
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.tenant_models import Project, ProjectMember, Task, Team, TeamMember, TeamProject, User
from app.modules.notifications.service import notify

MEMBER_ROLES = ("employee", "manager", "hr")
LEADER_ROLES = ("employee", "manager")


# ---- lookups ------------------------------------------------------------------------------------

def team_member_ids(db: Session, team_id: int) -> list[int]:
    return list(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team_id)))


def team_of(db: Session, user_id: int) -> Team | None:
    return db.scalar(select(Team).join(TeamMember, TeamMember.team_id == Team.id).where(TeamMember.user_id == user_id))


def led_team_ids_for_project(db: Session, user_id: int, project_id: int) -> list[int]:
    return list(db.scalars(
        select(Team.id).join(TeamProject, TeamProject.team_id == Team.id)
        .where(Team.leader_id == user_id, Team.is_active.is_(True), TeamProject.project_id == project_id)
    ))


def leads_project(db: Session, user_id: int, project_id: int) -> bool:
    """Is `user_id` the leader of an active team that this project is allocated to?"""
    return bool(led_team_ids_for_project(db, user_id, project_id))


def team_leader_ids_for_user(db: Session, user_id: int) -> list[int]:
    """Leader (if any) of the team the user belongs to."""
    return [i for i in db.scalars(
        select(Team.leader_id).join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id, Team.leader_id.is_not(None), Team.is_active.is_(True))
    ) if i != user_id]


def leaders_for_task(db: Session, project_id: int, assignee_id: int | None) -> list[int]:
    """Leaders of the teams (allocated to the project) the assignee belongs to; falls back to all project leaders."""
    q = select(Team.leader_id).join(TeamProject, TeamProject.team_id == Team.id).where(
        TeamProject.project_id == project_id, Team.leader_id.is_not(None), Team.is_active.is_(True))
    if assignee_id:
        q = q.where(exists().where(TeamMember.team_id == Team.id, TeamMember.user_id == assignee_id))
    return sorted(set(db.scalars(q)))


def assignable_ids(db: Session, user_id: int, project_id: int) -> set[int]:
    """People a team leader may give work to on this project: the members of the teams they lead for it."""
    ids: set[int] = set()
    for tid in led_team_ids_for_project(db, user_id, project_id):
        ids.update(team_member_ids(db, tid))
    return ids


# ---- project membership sync --------------------------------------------------------------------

def team_project_ids(db: Session, team_id: int) -> list[int]:
    return list(db.scalars(select(TeamProject.project_id).where(TeamProject.team_id == team_id)))


def grant_project_access(db: Session, project_ids: list[int], user_ids: list[int]) -> None:
    for pid in project_ids:
        have = set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == pid, ProjectMember.user_id.in_(user_ids))))
        for uid in set(user_ids) - have:
            db.add(ProjectMember(project_id=pid, user_id=uid))


def revoke_project_access(db: Session, project_ids: list[int], user_ids: list[int]) -> None:
    """Drop project membership unless the person still owns the project, has tasks in it or is covered by another team."""
    for pid in project_ids:
        project = db.get(Project, pid)
        if project is None:
            continue
        for uid in user_ids:
            if uid == project.owner_id:
                continue
            if db.scalar(select(Task.id).where(Task.project_id == pid, Task.assignee_id == uid).limit(1)) is not None:
                continue
            covered = db.scalar(
                select(TeamMember.user_id).join(TeamProject, TeamProject.team_id == TeamMember.team_id)
                .where(TeamProject.project_id == pid, TeamMember.user_id == uid).limit(1))
            if covered is not None:
                continue
            row = db.get(ProjectMember, (pid, uid))
            if row is not None:
                db.delete(row)


# ---- leaving a team -----------------------------------------------------------------------------

def release_user(db: Session, team: Team, user_id: int, *, unassign_tasks: bool = True) -> dict:
    """Remove a member from a team: clear leadership, free their open team-project tasks, trim project access.

    Returns {"unassigned_tasks": n, "was_leader": bool}. The caller commits and audits.
    """
    row = db.get(TeamMember, (team.id, user_id))
    if row is not None:
        db.delete(row)
    was_leader = team.leader_id == user_id
    if was_leader:
        team.leader_id = None
    pids = team_project_ids(db, team.id)
    freed = 0
    if unassign_tasks and pids:
        tasks = db.scalars(select(Task).where(Task.project_id.in_(pids), Task.assignee_id == user_id, Task.status != "done")).all()
        owners: dict[int, int] = {}
        for t in tasks:
            t.assignee_id, t.is_blocked, t.blocker_note = None, False, None
            owners[t.project_id] = owners.get(t.project_id, 0) + 1
        freed = len(tasks)
        notice = [team.leader_id, team.manager_id] + [db.get(Project, p).owner_id for p in owners]
        if freed:
            notify(db, [i for i in notice if i and i != user_id], "Tasks need reassignment",
                   f"A member left team {team.name}; {freed} open task(s) are now unassigned.", "team", f"/teams/{team.id}")
    db.flush()
    revoke_project_access(db, pids, [user_id])
    return {"unassigned_tasks": freed, "was_leader": was_leader}


def release_from_all_teams(db: Session, user: User) -> None:
    """Offboarding / role change: leave the team and stop owning or leading any team. Caller commits."""
    team = team_of(db, user.id)
    if team is not None:
        release_user(db, team, user.id, unassign_tasks=False)
    for t in db.scalars(select(Team).where(Team.manager_id == user.id)):
        t.manager_id = None
    for t in db.scalars(select(Team).where(Team.leader_id == user.id)):
        t.leader_id = None


def release_if_branch_mismatch(db: Session, user: User) -> list[int]:
    """After a branch change: leave a team of another branch and stop owning teams of another branch."""
    left: list[int] = []
    team = team_of(db, user.id)
    if team is not None and team.branch_id is not None and team.branch_id != user.branch_id:
        release_user(db, team, user.id)
        notify(db, [i for i in (team.leader_id, team.manager_id) if i], "Team member moved",
               f"{user.full_name} left team {team.name} after a branch change.", "team", f"/teams/{team.id}")
        left.append(team.id)
    for t in db.scalars(select(Team).where(Team.manager_id == user.id, Team.branch_id.is_not(None))):
        if user.branch_id is not None and t.branch_id != user.branch_id:
            t.manager_id = None
            left.append(t.id)
    return left
