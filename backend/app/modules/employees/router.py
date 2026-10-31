from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app import storage
from app.access import can_manage_user, has_permission, same_branch, user_scope
from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import (
    Attendance, AuditLog, Branch, ChecklistItem, CommException, ConversationMember, DailyUpdate, Department, EmployeeDocument, LeaveBalance,
    EmployeeEvent, LeaveRequest, Message, Notification, Project, ProjectMember, Task, Team, TeamMember, TeamProject, TeamReport, User,
)
from app.deps import Ctx, get_ctx, require_roles
from app.modules.employees.schemas import DOC_TYPES, ChecklistUpdate, DepartmentIn, DepartmentUpdate, DocumentVerification, EmployeeCreate, EmployeeUpdate, PasswordReset
from app.modules.employees import events as ev
from app.modules.leave.service import ensure_balances
from app.modules.notifications.service import notify
from app.modules.teams.service import release_from_all_teams, release_if_branch_mismatch
from app.modules.webhooks.service import emit

router = APIRouter(tags=["employees"])
hr_or_founder = require_roles("hr", "founder")


def employee_staff(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    """HR and founders, or a manager holding `employees.manage` (limited to their own reports; may only add plain employees)."""
    if ctx.role in ("hr", "founder"):
        return ctx
    if ctx.role == "manager" and has_permission(ctx.user, "employees.manage"):
        return ctx
    raise Forbidden("Only HR, founders and managers with the 'employees.manage' permission can do this")

ONBOARDING = ["Sign employment contract", "Submit identity documents", "IT equipment & accounts", "Orientation with manager"]
OFFBOARDING = ["Return company assets", "Revoke system access", "Knowledge transfer", "Exit interview", "Final settlement"]


def ser(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "status": u.status,
        "is_active": u.is_active, "department_id": u.department_id, "manager_id": u.manager_id,
        "designation": u.designation, "phone": u.phone, "hire_date": u.hire_date,
        "offboarded_at": u.offboarded_at, "created_at": u.created_at, "avatar_v": u.avatar_name,
        "employee_code": u.employee_code, "branch_id": u.branch_id, "location": u.location,
    }


def ser_public(u: User) -> dict:
    return {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "designation": u.designation,
            "department_id": u.department_id, "manager_id": u.manager_id, "avatar_v": u.avatar_name,
            "branch_id": u.branch_id, "employee_code": u.employee_code}


def _validate_refs(ctx: Ctx, department_id, manager_id, user_id: int | None = None, branch_id: int | None = None) -> None:
    if department_id is not None:
        dept = ctx.db.get(Department, department_id)
        if dept is None:
            raise AppError("Department does not exist")
        if dept.status != "active":
            raise AppError("This department is inactive and cannot receive new people")
    if manager_id is not None:
        mgr = ctx.db.get(User, manager_id)
        if mgr is None or not mgr.is_active:
            raise AppError("Manager does not exist or is inactive")
        if branch_id is not None and mgr.branch_id is not None and mgr.branch_id != branch_id:
            raise AppError("The reporting manager must belong to the same branch")
        # reject reporting cycles
        cur, seen = mgr, set()
        while cur is not None and cur.id not in seen:
            if user_id is not None and cur.id == user_id:
                raise AppError("Reporting hierarchy cannot contain a cycle")
            seen.add(cur.id)
            cur = ctx.db.get(User, cur.manager_id) if cur.manager_id else None


def _check_role_grant(ctx: Ctx, new_role: str) -> None:
    if new_role in ("founder", "manager", "hr") and ctx.role != "founder":
        raise Forbidden(f"Only a founder can grant the {new_role} role")


def _check_branch_change(ctx: Ctx, branch_id: int | None) -> None:
    """Only founders assign people to branches; the branch must exist and be active."""
    if ctx.role != "founder":
        raise Forbidden("Only a founder can assign branches")
    if branch_id is not None:
        b = ctx.db.get(Branch, branch_id)
        if b is None:
            raise AppError("Branch does not exist")
        if not b.is_active:
            raise AppError("This branch is inactive")


def _get_user(ctx: Ctx, user_id: int) -> User:
    u = ctx.db.get(User, user_id)
    if u is None:
        raise NotFound("Employee not found")
    return u


def _can_admin(ctx: Ctx, target: User) -> bool:
    """HR/founder administration of this account (HR: own branch only; never founders or board members)."""
    if ctx.role == "hr" and target.role in ("founder", "board_member"):
        return False
    return can_manage_user(ctx, target)


def _can_view(ctx: Ctx, target: User) -> bool:
    if target.id == ctx.user.id or _can_admin(ctx, target):
        return True
    return ctx.role == "manager" and target.manager_id == ctx.user.id and same_branch(ctx.user, target)


def _admin_user(ctx: Ctx, user_id: int) -> User:
    """Load an account for administration; out-of-scope accounts look non-existent (no cross-branch leakage)."""
    u = _get_user(ctx, user_id)
    if not _can_admin(ctx, u):
        if ctx.role in ("hr", "manager") and u.role in ("founder", "board_member"):
            raise Forbidden(f"Only a founder can manage a {u.role.replace('_', ' ')}")
        raise NotFound("Employee not found")
    return u


# ---- employees ------------------------------------------------------------------------------

@router.get("/employees/directory")
def directory(ctx: Ctx = Depends(get_ctx)):
    """Minimal active-employee list for pickers, org chart and assignment (all roles except board members).

    Data minimisation: founders see everybody. Everyone else sees their own branch plus people who belong to no branch
    (the founder), never board members, and an employee gets no e-mail address or employee code for anybody but themself.
    A person with no branch assignment (company-wide HR/manager) keeps the company-wide list."""
    if ctx.role == "board_member":
        raise Forbidden("Board members have no access to employee data")
    stmt = select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    if ctx.role != "founder":
        stmt = stmt.where(User.role != "board_member")
        if ctx.user.branch_id is not None:
            stmt = stmt.where(or_(User.branch_id == ctx.user.branch_id, User.branch_id.is_(None)))
    items = []
    for u in ctx.db.scalars(stmt):
        item = ser_public(u)
        if ctx.role == "employee" and u.id != ctx.user.id:
            item["email"] = None
            item["employee_code"] = None
        items.append(item)
    return {"items": items}


@router.get("/employees/{user_id}/card")
def colleague_card(user_id: int, ctx: Ctx = Depends(get_ctx)):
    """What a colleague may see about a colleague: the directory-level facts, never contact details, personal data, documents,
    history or pay. People visible here are the ones the directory lists (own branch plus branch-less people; founders see all).
    `can_open` says whether the caller may also open the full record (the same rule GET /employees/{id} applies)."""
    if ctx.role == "board_member":
        raise Forbidden("Board members have no access to employee data")
    u = ctx.db.get(User, user_id)
    colleague = u is not None and u.is_active and (
        ctx.role == "founder"
        or (u.role != "board_member" and (ctx.user.branch_id is None or u.branch_id is None or u.branch_id == ctx.user.branch_id)))
    # people the caller administers stay reachable when suspended or offboarded (HR must open them to reinstate or review)
    if not (colleague or (u is not None and _can_view(ctx, u))):
        raise NotFound("Employee not found")
    dept = ctx.db.get(Department, u.department_id) if u.department_id else None
    branch = ctx.db.get(Branch, u.branch_id) if u.branch_id else None
    mgr = ctx.db.get(User, u.manager_id) if u.manager_id else None
    tm = ctx.db.scalar(select(TeamMember).where(TeamMember.user_id == u.id).limit(1))
    team = ctx.db.get(Team, tm.team_id) if tm else None
    reports = ctx.db.scalar(select(func.count(User.id)).where(User.manager_id == u.id, User.is_active.is_(True))) or 0
    return {"id": u.id, "full_name": u.full_name, "designation": u.designation, "role": u.role, "avatar_v": u.avatar_name,
            "department": dept.name if dept else None, "branch": branch.name if branch else None, "location": u.location,
            "manager": {"id": mgr.id, "name": mgr.full_name} if mgr and mgr.is_active else None, "team": team.name if team else None,
            "joined": u.hire_date, "direct_reports": reports,
            # e-mail is shared with colleagues who administer people (not with plain employees), as in the directory
            "email": u.email if ctx.role != "employee" or u.id == ctx.user.id else None,
            "can_open": _can_view(ctx, u)}


@router.get("/employees/my-team")
def my_team(ctx: Ctx = Depends(require_roles("manager", "hr", "founder"))):
    rows = ctx.db.scalars(select(User).where(User.manager_id == ctx.user.id, User.is_active.is_(True)).order_by(User.full_name))
    return {"items": [ser(u) for u in rows]}


@router.get("/employees")
def list_employees(
    q: str | None = None, department_id: int | None = None, role: str | None = None, status: str | None = None,
    branch_id: int | None = None, sort: Literal["full_name", "hire_date", "status", "role", "employee_code"] = "full_name",
    order: Literal["asc", "desc"] = "asc", params: PageParams = Depends(), ctx: Ctx = Depends(employee_staff),
):
    col = getattr(User, sort)
    stmt = select(User).where(user_scope(ctx)).order_by(col.desc() if order == "desc" else col.asc(), User.id)
    if ctx.role == "hr":
        stmt = stmt.where(User.role.not_in(("founder", "board_member")))
    if branch_id:
        stmt = stmt.where(User.branch_id == branch_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    return paginate(ctx.db, stmt, params, ser)


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeCreate, ctx: Ctx = Depends(employee_staff)):
    if ctx.role == "manager":
        if body.role not in ("employee", "hr"):
            raise Forbidden("Managers can add employees and HR staff only")
        body.manager_id = ctx.user.id  # a manager's new hires report to them
    else:
        _check_role_grant(ctx, body.role)
    branch_id = body.branch_id
    if "branch_id" in body.model_fields_set and branch_id is not None:
        _check_branch_change(ctx, branch_id)
    if ctx.role in ("hr", "manager") and ctx.user.branch_id is not None:
        branch_id = ctx.user.branch_id  # branch HR / branch managers hire into their own branch only
    _validate_refs(ctx, body.department_id, body.manager_id, branch_id=branch_id)
    if body.employee_code and ctx.db.scalar(select(User.id).where(func.lower(User.employee_code) == body.employee_code.lower())):
        raise Conflict("This employee ID is already in use")
    with platform_session() as pdb:
        max_users = pdb.get(Company, ctx.company_id).max_users
    if (ctx.db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0) >= max_users:
        raise AppError("User limit reached for this company plan", status_code=402, code="plan_limit")
    if ctx.db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise Conflict("An employee with this email already exists")
    u = User(
        email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role=body.role,
        department_id=body.department_id, manager_id=body.manager_id, designation=body.designation, phone=body.phone,
        hire_date=body.hire_date or utcnow().date(), status="pending_approval" if ctx.role == "manager" else "onboarding", branch_id=branch_id,
        employee_code=body.employee_code.upper() if body.employee_code else None,
        location=body.location or (ctx.db.get(Branch, branch_id).city if branch_id else None),
    )
    ctx.db.add(u)
    ctx.db.flush()
    if not u.employee_code:
        u.employee_code = f"EMP-{u.id:04d}"
    ev.record(ctx.db, u.id, "joined", actor_id=ctx.user.id, effective=u.hire_date, to={"designation": u.designation, "role": u.role})
    pending = ctx.role == "manager"
    if pending:
        u.is_active = False  # cannot sign in or be assigned work until HR/founder approves the joining
    ensure_balances(ctx.db, u, utcnow().date().year)
    for t in ONBOARDING:
        ctx.db.add(ChecklistItem(user_id=u.id, kind="onboarding", title=t))
    audit(ctx, "employee.created", "user", u.id, {"role": u.role, "branch_id": u.branch_id, "employee_code": u.employee_code})
    if pending:
        # a new HR account is approved by a founder only; other joinings by a founder or the branch's HR
        hr_ok = and_(User.role == "hr", or_(User.branch_id.is_(None), User.branch_id == u.branch_id)) if u.role != "hr" else User.id < 0
        approvers = [a.id for a in ctx.db.scalars(select(User).where(User.is_active.is_(True), or_(User.role == "founder", hr_ok)))]
        notify(ctx.db, approvers, "Employee awaiting approval", f"{ctx.user.full_name} added {u.full_name}. Approve the joining to activate the account.", "approval", f"/employees/{u.id}")
    else:
        notify(ctx.db, [u.id], "Welcome to the team", "Your account is ready. Complete your onboarding checklist.", "onboarding")
    if u.manager_id and not pending:
        notify(ctx.db, [u.manager_id], "New team member", f"{u.full_name} now reports to you.", "team")
    emit(ctx.db, "employee.created", {"id": u.id, "email": u.email, "role": u.role})
    ctx.db.commit()
    return ser(u)


@router.get("/employees/{user_id}")
def get_employee(user_id: int, ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if not _can_view(ctx, u):
        raise Forbidden()
    data = ser(u)
    # Include team and projects info for this employee
    tm = ctx.db.scalar(select(TeamMember).where(TeamMember.user_id == u.id).limit(1))
    if tm:
        team = ctx.db.get(Team, tm.team_id)
        if team:
            leader = ctx.db.get(User, team.leader_id) if team.leader_id else None
            manager = ctx.db.get(User, team.manager_id) if team.manager_id else None
            data["team"] = {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "is_active": team.is_active,
                "leader": ser_public(leader) if leader else None,
                "manager": ser_public(manager) if manager else None,
            }
            # Projects allocated to this team
            proj_links = ctx.db.execute(
                select(TeamProject, Project).join(Project, Project.id == TeamProject.project_id)
                .where(TeamProject.team_id == team.id).order_by(Project.name)
            ).all()
            user_projects = []
            for _, p in proj_links:
                tasks = ctx.db.scalars(
                    select(Task).where(Task.project_id == p.id, Task.assignee_id == u.id)
                    .order_by(Task.due_date.is_(None), Task.due_date, Task.id)
                ).all()
                teammate_ids = set(ctx.db.scalars(
                    select(Task.assignee_id).where(Task.project_id == p.id, Task.assignee_id.is_not(None), Task.assignee_id != u.id)
                ).all())
                working_mems = ctx.db.scalars(select(User).where(User.id.in_(teammate_ids))).all() if teammate_ids else []
                user_projects.append({
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "due_date": p.due_date,
                    "tasks": [{
                        "id": tk.id, "title": tk.title, "status": tk.status, "due_date": tk.due_date,
                        "is_blocked": tk.is_blocked, "progress": tk.progress, "priority": tk.priority
                    } for tk in tasks],
                    "teammates": [ser_public(w) for w in working_mems]
                })
            data["projects"] = user_projects
    else:
        data["team"] = None
        data["projects"] = []
    return data


def _record_changes(ctx: Ctx, u: User, before: dict) -> None:
    """Edits made on the employee form land in the same history as the dedicated lifecycle actions."""
    def ref(model, i):
        o = ctx.db.get(model, i) if i else None
        return None if o is None else {"id": o.id, "name": getattr(o, "full_name", None) or o.name}
    pairs = (("department_id", "department_changed", Department), ("manager_id", "manager_changed", User), ("branch_id", "branch_changed", Branch))
    for field, kind, model in pairs:
        if getattr(u, field) != before[field]:
            ev.record(ctx.db, u.id, kind, actor_id=ctx.user.id, frm=ref(model, before[field]), to=ref(model, getattr(u, field)))
    if u.role != before["role"]:
        ev.record(ctx.db, u.id, "role_changed", actor_id=ctx.user.id, frm={"role": before["role"]}, to={"role": u.role})
    if u.designation != before["designation"]:
        ev.record(ctx.db, u.id, "promoted", actor_id=ctx.user.id, frm={"designation": before["designation"]}, to={"designation": u.designation}, note="Edited on the employee record")
    if before["status"] == "onboarding" and u.status == "active":
        ev.record(ctx.db, u.id, "activated", actor_id=ctx.user.id)


@router.patch("/employees/{user_id}")
def update_employee(user_id: int, body: EmployeeUpdate, ctx: Ctx = Depends(employee_staff)):
    chk = _get_user(ctx, user_id)
    if ctx.role == "manager" and chk.manager_id != ctx.user.id:
        raise Forbidden("Managers can only delete their direct reports")
    u = _admin_user(ctx, user_id)
    data = body.model_dump(exclude_unset=True)
    if ctx.role == "manager":
        if "role" in data and data["role"] != u.role:
            raise Forbidden("Managers cannot change employee roles")
        if "branch_id" in data and data["branch_id"] != u.branch_id:
            raise Forbidden("Managers cannot change branches")
    if u.status == "pending_approval" and data.get("status"):
        raise AppError("This joining is awaiting approval; approve it first")
    if u.role == "founder" and ctx.role != "founder":
        raise Forbidden("Only a founder can modify a founder")
    if "role" in data and data["role"] is None:
        data.pop("role")
    if "role" in data and data["role"] != u.role:
        _check_role_grant(ctx, data["role"])
        if u.role in ("manager", "hr") and ctx.role != "founder":
            raise Forbidden(f"Only a founder can change a {u.role}'s role")
        if u.role == "founder" and data["role"] != "founder":
            if (ctx.db.scalar(select(func.count(User.id)).where(User.role == "founder", User.is_active.is_(True))) or 0) <= 1:
                raise AppError("A company must keep at least one founder")
    if "branch_id" in data:
        if data["branch_id"] != u.branch_id:
            _check_branch_change(ctx, data["branch_id"])
            if data["branch_id"] is not None and u.role not in ("employee", "manager", "hr"):
                raise AppError("Founders and board members are company-wide")
        else:
            data.pop("branch_id")
    if "employee_code" in data:
        code = (data["employee_code"] or "").upper()
        if not code:
            data.pop("employee_code")
        else:
            data["employee_code"] = code
            if ctx.db.scalar(select(User.id).where(func.lower(User.employee_code) == code.lower(), User.id != u.id)):
                raise Conflict("This employee ID is already in use")
    new_branch = data.get("branch_id", u.branch_id)
    if "manager_id" in data or "branch_id" in data:
        _validate_refs(ctx, data.get("department_id"), data.get("manager_id", u.manager_id), u.id, branch_id=new_branch)
    else:
        _validate_refs(ctx, data.get("department_id"), None, u.id)
    if data.get("manager_id") == u.id:
        raise AppError("An employee cannot report to themselves")
    before = {k: getattr(u, k) for k in ("department_id", "manager_id", "branch_id", "role", "designation", "status")}
    for k, v in data.items():
        setattr(u, k, v)
    if "branch_id" in data:
        ctx.db.flush()
        release_if_branch_mismatch(ctx.db, u)
    _record_changes(ctx, u, before)
    audit(ctx, "employee.updated", "user", u.id, {"fields": sorted(data)})
    ctx.db.commit()
    return ser(u)


@router.post("/employees/{user_id}/approve")
def approve_joining(user_id: int, ctx: Ctx = Depends(employee_staff)):
    """HR/founder or manager approve a joining: the account becomes active and can sign in."""
    if ctx.role == "manager":
        u = _get_user(ctx, user_id)
        if u.manager_id != ctx.user.id:
            raise Forbidden("You can only approve employees who report to you")
        if u.role not in ("employee", "hr"):
            raise Forbidden("Managers can only approve employee or HR accounts")
    else:
        u = _admin_user(ctx, user_id)
        if u.role == "hr" and ctx.role != "founder":
            raise Forbidden("Only a founder can approve a new HR account")
    if u.status != "pending_approval":
        raise Conflict("This employee is not awaiting approval")
    with platform_session() as pdb:
        max_users = pdb.get(Company, ctx.company_id).max_users
    if (ctx.db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0) >= max_users:
        raise AppError("User limit reached for this company plan", status_code=402, code="plan_limit")
    u.status, u.is_active = "active", True
    ev.record(ctx.db, u.id, "activated", actor_id=ctx.user.id, note="Joining approved")
    notify(ctx.db, [i for i in {u.manager_id} if i and i != ctx.user.id], "Joining approved", f"{u.full_name} was approved and can now sign in.", "approval", f"/employees/{u.id}")
    notify(ctx.db, [u.id], "Welcome to the team", "Your account is ready. Complete your onboarding checklist.", "onboarding")
    audit(ctx, "employee.approved", "user", u.id, {"added_by": u.manager_id, "approved_by": ctx.user.id})
    emit(ctx.db, "employee.created", {"id": u.id, "email": u.email, "role": u.role})
    ctx.db.commit()
    return ser(u)


@router.post("/employees/{user_id}/reject", status_code=204)
def reject_joining(user_id: int, ctx: Ctx = Depends(employee_staff)):
    """Remove a pending joining: HR/founder decline it, or the manager declines/withdraws it."""
    if ctx.role == "manager":
        u = _get_user(ctx, user_id)
        if u.manager_id != ctx.user.id or u.status != "pending_approval":
            raise Forbidden("You can only delete a pending joining that you added")
    else:
        u = _admin_user(ctx, user_id)
    if u.status != "pending_approval":
        raise Conflict("Only a joining that is awaiting approval can be rejected")
    name, email, boss = u.full_name, u.email, u.manager_id
    for model in (ChecklistItem, LeaveBalance, Notification):
        ctx.db.query(model).filter(model.user_id == u.id).delete(synchronize_session=False)
    ctx.db.delete(u)
    notify(ctx.db, [boss] if boss else [], "Joining rejected", f"{name} was not approved.", "approval")
    audit(ctx, "employee.rejected", "user", user_id, {"name": name, "email": email, "rejected_by": ctx.user.id})
    ctx.db.commit()


@router.post("/employees/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, ctx: Ctx = Depends(employee_staff)):
    u = _admin_user(ctx, user_id)
    if u.role == "founder" and ctx.role != "founder":
        raise Forbidden("Only a founder can reset a founder's password")
    u.password_hash = hash_password(body.new_password)
    u.session_version = (u.session_version or 0) + 1  # sessions opened with the old password must not survive a reset
    audit(ctx, "employee.password_reset", "user", u.id)
    ctx.db.commit()


@router.post("/employees/{user_id}/mfa/reset", status_code=204)
def reset_mfa(user_id: int, ctx: Ctx = Depends(employee_staff)):
    """Lost phone: switch off someone's two-step verification so they can sign in and enrol again. Ends their sessions."""
    u = _admin_user(ctx, user_id)
    if u.id == ctx.user.id:
        raise AppError("Use your profile to turn off your own two-step verification")
    if u.role == "founder" and ctx.role != "founder":
        raise Forbidden("Only a founder can reset a founder's two-step verification")
    u.mfa_enabled, u.mfa_secret_enc, u.mfa_last_step, u.mfa_recovery = False, None, None, None
    u.session_version = (u.session_version or 0) + 1
    audit(ctx, "employee.mfa_reset", "user", u.id)
    ctx.db.commit()


class OffboardIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


@router.post("/employees/{user_id}/offboard")
def offboard(user_id: int, body: OffboardIn | None = None, ctx: Ctx = Depends(employee_staff)):
    chk = _get_user(ctx, user_id)
    if ctx.role == "manager" and chk.manager_id != ctx.user.id:
        raise Forbidden("Managers can only delete their direct reports")
    u = _admin_user(ctx, user_id)
    if u.id == ctx.user.id:
        raise AppError("You cannot offboard yourself")
    if u.role == "founder":
        if ctx.role != "founder":
            raise Forbidden("Only a founder can offboard a founder")
        if (ctx.db.scalar(select(func.count(User.id)).where(User.role == "founder", User.is_active.is_(True))) or 0) <= 1:
            raise AppError("A company must keep at least one founder")
    if u.status == "offboarded":
        raise Conflict("Employee is already offboarded")
    if u.status == "pending_approval":
        raise Conflict("This joining is awaiting approval; reject it instead")
    prior = u.status
    u.status, u.is_active, u.offboarded_at = "offboarded", False, utcnow()
    u.session_version = (u.session_version or 0) + 1
    ev.record(ctx.db, u.id, "offboarded", actor_id=ctx.user.id, frm={"status": prior}, note=(body.reason if body else None))
    for t in OFFBOARDING:
        ctx.db.add(ChecklistItem(user_id=u.id, kind="offboarding", title=t))
    # Orphaned work: unassign open tasks and tell the project owners; re-parent direct reports.
    open_tasks = ctx.db.scalars(select(Task).where(Task.assignee_id == u.id, Task.status != "done")).all()
    owners: dict[int, int] = {}
    for t in open_tasks:
        t.assignee_id = None
        proj = ctx.db.get(Project, t.project_id)
        owners[proj.owner_id] = owners.get(proj.owner_id, 0) + 1
    for owner_id, n in owners.items():
        notify(ctx.db, [owner_id], "Tasks need reassignment", f"{u.full_name} left; {n} task(s) are now unassigned.", "task")
    for rep in ctx.db.scalars(select(User).where(User.manager_id == u.id)):
        rep.manager_id = u.manager_id
    release_from_all_teams(ctx.db, u)
    audit(ctx, "employee.offboarded", "user", u.id)
    emit(ctx.db, "employee.offboarded", {"id": u.id, "email": u.email})
    ctx.db.commit()
    return ser(u)


def _has_history(ctx: Ctx, u: User) -> bool:
    """Any business record that would be lost or orphaned by a hard delete."""
    checks = (
        select(Attendance.id).where(Attendance.user_id == u.id), select(DailyUpdate.id).where(DailyUpdate.user_id == u.id),
        select(LeaveRequest.id).where(LeaveRequest.user_id == u.id),
        select(Task.id).where((Task.assignee_id == u.id) | (Task.created_by == u.id)),
        select(Project.id).where(Project.owner_id == u.id), select(ProjectMember.user_id).where(ProjectMember.user_id == u.id),
        select(Message.id).where(Message.sender_id == u.id), select(TeamReport.id).where(TeamReport.author_id == u.id), select(AuditLog.id).where(AuditLog.actor_id == u.id),
    )
    return any(ctx.db.scalar(c.limit(1)) is not None for c in checks)


@router.delete("/employees/{user_id}", status_code=204)
def delete_employee(user_id: int, ctx: Ctx = Depends(employee_staff)):
    """Permanently delete an account that has no history (no tasks, updates, leave, messages...).

    Anyone with work history must be offboarded instead; the database refuses deletes that would orphan records.
    """
    chk = _get_user(ctx, user_id)
    if ctx.role == "manager" and chk.manager_id != ctx.user.id:
        raise Forbidden("Managers can only delete their direct reports")
    u = _admin_user(ctx, user_id)
    if u.id == ctx.user.id:
        raise AppError("You cannot delete your own account")
    if u.role in ("founder", "board_member"):
        raise Forbidden(f"A {u.role.replace('_', ' ')} cannot be deleted here")
    if _has_history(ctx, u):
        raise Conflict("This person has work history and cannot be deleted. Offboard them instead.")
    files = [d.stored_name for d in ctx.db.scalars(select(EmployeeDocument).where(EmployeeDocument.user_id == u.id))]
    if u.avatar_name:
        files.append(u.avatar_name)
    name, email = u.full_name, u.email
    try:
        with ctx.db.begin_nested():
            for model in (ChecklistItem, LeaveBalance, Notification, EmployeeDocument, ConversationMember, CommException):
                ctx.db.query(model).filter(model.user_id == u.id).delete(synchronize_session=False)
            for rep in ctx.db.scalars(select(User).where(User.manager_id == u.id)):
                rep.manager_id = u.manager_id
            ctx.db.delete(u)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("This person has work history and cannot be deleted. Offboard them instead.")
    audit(ctx, "employee.deleted", "user", user_id, {"name": name, "email": email})
    ctx.db.commit()
    for f in files:
        storage.delete_file(ctx.company_id, f)


# ---- onboarding / offboarding checklist -------------------------------------------------------

@router.get("/employees/{user_id}/checklist")
def checklist(user_id: int, ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if not _can_view(ctx, u):
        raise Forbidden()
    rows = ctx.db.scalars(select(ChecklistItem).where(ChecklistItem.user_id == user_id).order_by(ChecklistItem.id))
    return {"items": [{"id": c.id, "kind": c.kind, "title": c.title, "done": c.done, "done_at": c.done_at} for c in rows]}


@router.patch("/checklist/{item_id}")
def update_checklist(item_id: int, body: ChecklistUpdate, ctx: Ctx = Depends(hr_or_founder)):
    c = ctx.db.get(ChecklistItem, item_id)
    if c is None or not _can_admin(ctx, _get_user(ctx, c.user_id)):
        raise NotFound()
    c.done, c.done_at = body.done, (utcnow() if body.done else None)
    if c.kind == "offboarding" and body.done:
        left = ctx.db.scalar(select(func.count(ChecklistItem.id)).where(
            ChecklistItem.user_id == c.user_id, ChecklistItem.kind == "offboarding", ChecklistItem.done.is_(False), ChecklistItem.id != c.id))
        if left == 0 and not ctx.db.scalar(select(EmployeeEvent.id).where(EmployeeEvent.user_id == c.user_id, EmployeeEvent.kind == "exit_cleared")):
            ev.record(ctx.db, c.user_id, "exit_cleared", actor_id=ctx.user.id, note="All exit clearance items completed")
    if c.kind == "onboarding":
        pending = ctx.db.scalar(select(func.count(ChecklistItem.id)).where(
            ChecklistItem.user_id == c.user_id, ChecklistItem.kind == "onboarding", ChecklistItem.done.is_(False), ChecklistItem.id != c.id))
        u = ctx.db.get(User, c.user_id)
        if body.done and pending == 0 and u.status == "onboarding":
            u.status = "active"
    ctx.db.commit()
    return {"id": c.id, "done": c.done}


# ---- documents ------------------------------------------------------------------------------

def _ser_doc(d: EmployeeDocument) -> dict:
    expiring = d.expiry_date is not None and d.expiry_date <= utcnow().date() + timedelta(days=30)
    return {"id": d.id, "name": d.name, "doc_type": d.doc_type, "size": d.size, "created_at": d.created_at,
            "expiry_date": d.expiry_date, "verification_status": d.verification_status, "verified_at": d.verified_at,
            "is_expired": d.expiry_date is not None and d.expiry_date < utcnow().date(), "expires_soon": expiring}


@router.post("/employees/{user_id}/documents", status_code=201)
async def upload_document(user_id: int, file: UploadFile = File(...), doc_type: str = Form("other"), expiry_date: str | None = Form(None), ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if not (_can_admin(ctx, u) or u.id == ctx.user.id):
        raise Forbidden()
    if doc_type not in DOC_TYPES:
        raise AppError(f"Unknown document type. Use one of: {', '.join(DOC_TYPES)}")
    expiry = None
    if expiry_date:
        try:
            expiry = date.fromisoformat(expiry_date)
        except ValueError:
            raise AppError("Expiry date must be a valid date (YYYY-MM-DD)") from None
    name, stored, size = await storage.save_upload(ctx.company_id, file)
    d = EmployeeDocument(user_id=u.id, name=name, doc_type=doc_type, stored_name=stored, size=size, uploaded_by=ctx.user.id, expiry_date=expiry)
    ctx.db.add(d)
    audit(ctx, "employee.document_uploaded", "user", u.id, {"name": name, "doc_type": doc_type})
    ctx.db.commit()
    return _ser_doc(d)


@router.get("/employees/{user_id}/documents")
def list_documents(user_id: int, ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if not (_can_admin(ctx, u) or u.id == ctx.user.id):
        raise Forbidden()
    rows = ctx.db.scalars(select(EmployeeDocument).where(EmployeeDocument.user_id == user_id).order_by(EmployeeDocument.id.desc()))
    return {"items": [_ser_doc(d) for d in rows]}


@router.patch("/documents/{doc_id}/verification")
def verify_document(doc_id: int, body: DocumentVerification, ctx: Ctx = Depends(hr_or_founder)):
    """HR/founders mark a document verified or rejected. People cannot verify their own documents."""
    d = ctx.db.get(EmployeeDocument, doc_id)
    if d is None or not _can_admin(ctx, _get_user(ctx, d.user_id)):
        raise NotFound()
    if d.user_id == ctx.user.id:
        raise Forbidden("You cannot verify your own documents")
    d.verification_status = body.status
    d.verified_by = ctx.user.id if body.status != "pending" else None
    d.verified_at = utcnow() if body.status != "pending" else None
    audit(ctx, "employee.document_verified", "user", d.user_id, {"document_id": d.id, "status": body.status})
    ctx.db.commit()
    return _ser_doc(d)


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: int, ctx: Ctx = Depends(get_ctx)):
    d = ctx.db.get(EmployeeDocument, doc_id)
    if d is None:
        raise NotFound()
    if not (d.user_id == ctx.user.id or _can_admin(ctx, _get_user(ctx, d.user_id))):
        raise Forbidden()
    return FileResponse(storage.path_for(ctx.company_id, d.stored_name), filename=d.name, headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, ctx: Ctx = Depends(hr_or_founder)):
    d = ctx.db.get(EmployeeDocument, doc_id)
    if d is None:
        raise NotFound()
    if not _can_admin(ctx, _get_user(ctx, d.user_id)):
        raise NotFound()
    stored = d.stored_name
    ctx.db.delete(d)
    audit(ctx, "employee.document_deleted", "user", d.user_id)
    ctx.db.commit()
    storage.delete_file(ctx.company_id, stored)


# ---- profile photo (every role may change their OWN photo; anyone in the company may view it) -----

@router.post("/auth/me/avatar")
async def upload_my_avatar(file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    stored = await storage.save_avatar(ctx.company_id, file)
    old, ctx.user.avatar_name = ctx.user.avatar_name, stored
    audit(ctx, "profile.photo_uploaded", "user", ctx.user.id)
    ctx.db.commit()
    if old:
        storage.delete_file(ctx.company_id, old)
    return {"avatar_v": stored}


@router.delete("/auth/me/avatar", status_code=204)
def delete_my_avatar(ctx: Ctx = Depends(get_ctx)):
    old, ctx.user.avatar_name = ctx.user.avatar_name, None
    audit(ctx, "profile.photo_removed", "user", ctx.user.id)
    ctx.db.commit()
    if old:
        storage.delete_file(ctx.company_id, old)


@router.post("/employees/{user_id}/avatar")
async def upload_employee_avatar(user_id: int, file: UploadFile = File(...), ctx: Ctx = Depends(employee_staff)):
    """HR/founder set an employee's photo (HR only within their branch)."""
    u = _admin_user(ctx, user_id)
    stored = await storage.save_avatar(ctx.company_id, file)
    old, u.avatar_name = u.avatar_name, stored
    audit(ctx, "employee.photo_uploaded", "user", u.id)
    ctx.db.commit()
    if old:
        storage.delete_file(ctx.company_id, old)
    return {"avatar_v": stored}


@router.delete("/employees/{user_id}/avatar", status_code=204)
def delete_employee_avatar(user_id: int, ctx: Ctx = Depends(employee_staff)):
    u = _admin_user(ctx, user_id)
    old, u.avatar_name = u.avatar_name, None
    audit(ctx, "employee.photo_removed", "user", u.id)
    ctx.db.commit()
    if old:
        storage.delete_file(ctx.company_id, old)


@router.get("/users/{user_id}/avatar")
def get_avatar(user_id: int, ctx: Ctx = Depends(get_ctx)):
    u = ctx.db.get(User, user_id)
    if u is None or not u.avatar_name:
        raise NotFound()
    if ctx.role == "board_member" and u.role not in ("founder", "board_member"):
        raise NotFound()  # board members get no access to employee data, photos included
    path = storage.path_for(ctx.company_id, u.avatar_name)
    ctype = storage.sniff_image(path.read_bytes()[:16]) or "application/octet-stream"
    return FileResponse(path, media_type=ctype, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


# ---- departments ----------------------------------------------------------------------------

def _ser_dept(d: Department, count: int = 0, heads: dict | None = None, parents: dict | None = None) -> dict:
    return {"id": d.id, "code": d.code, "name": d.name, "description": d.description, "employee_count": count, "status": d.status,
            "head_id": d.head_id, "head_name": (heads or {}).get(d.head_id), "parent_id": d.parent_id, "parent_name": (parents or {}).get(d.parent_id),
            "cost_center": d.cost_center, "created_at": d.created_at}


def _dept_checks(ctx: Ctx, data: dict, current: Department | None) -> None:
    """Uniqueness of name/code, a valid head, and a parent that does not create a cycle."""
    for col, key, label in ((Department.name, "name", "name"), (Department.code, "code", "code")):
        val = data.get(key)
        if val:
            stmt = select(Department.id).where(func.lower(col) == val.lower())
            if current:
                stmt = stmt.where(Department.id != current.id)
            if ctx.db.scalar(stmt):
                raise Conflict(f"A department with this {label} already exists")
    if data.get("head_id") is not None:
        head = ctx.db.get(User, data["head_id"])
        if head is None or not head.is_active or head.role == "board_member":
            raise AppError("The department head must be an active employee")
    pid = data.get("parent_id")
    if pid is not None:
        if ctx.db.get(Department, pid) is None:
            raise AppError("Parent department does not exist")
        cur, seen = ctx.db.get(Department, pid), set()
        while cur is not None and cur.id not in seen:
            if current and cur.id == current.id:
                raise AppError("A department cannot be its own ancestor")
            seen.add(cur.id)
            cur = ctx.db.get(Department, cur.parent_id) if cur.parent_id else None


def _dept_out(ctx: Ctx, d: Department) -> dict:
    head = ctx.db.get(User, d.head_id) if d.head_id else None
    parent = ctx.db.get(Department, d.parent_id) if d.parent_id else None
    count = ctx.db.scalar(select(func.count(User.id)).where(User.department_id == d.id, User.is_active.is_(True))) or 0
    return _ser_dept(d, count, {head.id: head.full_name} if head else None, {parent.id: parent.name} if parent else None)


@router.get("/departments")
def list_departments(ctx: Ctx = Depends(get_ctx)):
    counts = dict(ctx.db.execute(select(User.department_id, func.count(User.id)).where(User.is_active.is_(True)).group_by(User.department_id)).all())
    rows = list(ctx.db.scalars(select(Department).order_by(Department.name)))
    heads = {u.id: u.full_name for u in ctx.db.scalars(select(User).where(User.id.in_([d.head_id for d in rows if d.head_id])))} if rows else {}
    parents = {d.id: d.name for d in rows}
    return {"items": [_ser_dept(d, counts.get(d.id, 0), heads, parents) for d in rows]}


@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn, ctx: Ctx = Depends(hr_or_founder)):
    data = body.model_dump()
    _dept_checks(ctx, data, None)
    d = Department(**data)
    ctx.db.add(d)
    ctx.db.flush()
    audit(ctx, "department.created", "department", d.id, {"name": body.name, "code": d.code})
    ctx.db.commit()
    return _dept_out(ctx, d)


@router.patch("/departments/{dept_id}")
def update_department(dept_id: int, body: DepartmentUpdate, ctx: Ctx = Depends(hr_or_founder)):
    d = ctx.db.get(Department, dept_id)
    if d is None:
        raise NotFound()
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "status") and v is None)}
    _dept_checks(ctx, data, d)
    for k, v in data.items():
        setattr(d, k, v)
    audit(ctx, "department.updated", "department", d.id, {"fields": sorted(data)})
    ctx.db.commit()
    return _dept_out(ctx, d)


@router.delete("/departments/{dept_id}", status_code=204)
def delete_department(dept_id: int, ctx: Ctx = Depends(hr_or_founder)):
    d = ctx.db.get(Department, dept_id)
    if d is None:
        raise NotFound()
    if ctx.db.scalar(select(func.count(User.id)).where(User.department_id == dept_id)):
        raise Conflict("Department still has employees")
    if ctx.db.scalar(select(func.count(Department.id)).where(Department.parent_id == dept_id)):
        raise Conflict("Department still has sub-departments. Move or delete them first")
    ctx.db.delete(d)
    audit(ctx, "department.deleted", "department", dept_id)
    ctx.db.commit()
