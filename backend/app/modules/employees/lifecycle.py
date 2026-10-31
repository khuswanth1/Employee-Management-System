"""Employee lifecycle: promotion, transfer, probation and confirmation, suspension, resignation, return, and the company org chart.

Every step is written to the append-only `employee_events` history. Access: HR (own branch) and founders administer lifecycle steps;
a person may resign or withdraw their own resignation; the person and their line manager can read the history, except internal
entries (suspensions, exit clearance); nobody else can. Changes apply immediately: `effective_date` (today or earlier) is recorded
for the history, nothing is scheduled for the future.
"""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.access import user_scope
from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import Branch, ChecklistItem, Department, EmployeeEvent, EmployeeProfile, User
from app.deps import Ctx, get_ctx, require_roles
from app.modules.employees import events as ev
from app.modules.employees.router import _admin_user, _can_admin, _can_view, _check_branch_change, _check_role_grant, _get_user, _validate_refs
from app.modules.leave.service import ensure_balances
from app.modules.notifications.service import notify
from app.modules.teams.service import release_from_all_teams, release_if_branch_mismatch

router = APIRouter(tags=["employee lifecycle"])
staff = require_roles("hr", "founder")


def _today() -> date:
    return utcnow().date()


def _admin(ctx: Ctx, user_id: int) -> User:
    if ctx.role not in ("hr", "founder"):
        raise Forbidden("Only HR and founders manage the employee lifecycle")
    return _admin_user(ctx, user_id)


def _effective(d: date | None, u: User) -> date:
    d = d or _today()
    if d > _today():
        raise AppError("The effective date cannot be in the future; changes apply immediately", status_code=422)
    if u.hire_date and d < u.hire_date:
        raise AppError(f"The effective date cannot be before the joining date ({u.hire_date.isoformat()})", status_code=422)
    return d


def _profile(ctx: Ctx, user_id: int) -> EmployeeProfile:
    p = ctx.db.get(EmployeeProfile, user_id)
    if p is None:
        p = EmployeeProfile(user_id=user_id)
        ctx.db.add(p)
        ctx.db.flush()
    return p


def _ref(obj) -> dict | None:
    return None if obj is None else {"id": obj.id, "name": getattr(obj, "full_name", None) or obj.name}


def _plan_limit(ctx: Ctx) -> None:
    with platform_session() as pdb:
        limit = pdb.get(Company, ctx.company_id).max_users
    if (ctx.db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0) >= limit:
        raise AppError("User limit reached for this company plan", status_code=402, code="plan_limit")


def _last_event(ctx: Ctx, user_id: int, *kinds: str) -> EmployeeEvent | None:
    return ctx.db.scalar(select(EmployeeEvent).where(EmployeeEvent.user_id == user_id, EmployeeEvent.kind.in_(kinds)).order_by(EmployeeEvent.id.desc()).limit(1))


# ================================================================== history

def ser_event(e: EmployeeEvent, names: dict) -> dict:
    return {"id": e.id, "user_id": e.user_id, "kind": e.kind, "effective_date": e.effective_date, "from": e.from_value, "to": e.to_value, "note": e.note,
            "by": names.get(e.created_by), "created_at": e.created_at}


@router.get("/employees/{user_id}/lifecycle")
def history(user_id: int, ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if not _can_view(ctx, u):
        raise NotFound("Employee not found")
    admin = ctx.role in ("hr", "founder") and _can_admin(ctx, u)
    q = select(EmployeeEvent).where(EmployeeEvent.user_id == u.id).order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc())
    if not admin:
        q = q.where(EmployeeEvent.kind.notin_(ev.INTERNAL))
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    clearance = None
    if admin and u.status == "offboarded":
        items = ctx.db.scalars(select(ChecklistItem).where(ChecklistItem.user_id == u.id, ChecklistItem.kind == "offboarding")).all()
        clearance = {"done": sum(1 for i in items if i.done), "total": len(items), "cleared": bool(items) and all(i.done for i in items)}
    p = ctx.db.get(EmployeeProfile, u.id)
    return {"user": {"id": u.id, "name": u.full_name, "status": u.status}, "can_manage": admin,
            "state": {"probation_end_date": p.probation_end_date if p else None, "confirmation_date": p.confirmation_date if p else None,
                      "last_working_date": p.last_working_date if p else None, "resigned": _last_event(ctx, u.id, "resignation_submitted", "resignation_withdrawn") is not None
                      and _last_event(ctx, u.id, "resignation_submitted", "resignation_withdrawn").kind == "resignation_submitted" and u.status != "offboarded"},
            "exit_clearance": clearance, "items": [ser_event(e, names) for e in ctx.db.scalars(q)]}


# ================================================================== promotion and transfers

class PromotionIn(BaseModel):
    effective_date: date | None = None
    designation: str | None = Field(None, min_length=2, max_length=120)
    job_level: str | None = Field(None, min_length=1, max_length=40)
    role: Literal["employee", "manager", "hr"] | None = None
    note: str | None = Field(None, max_length=1000)


@router.post("/employees/{user_id}/lifecycle/promotion")
def promote(user_id: int, body: PromotionIn, ctx: Ctx = Depends(get_ctx)):
    """A new title, job level and/or system role. Changing the role is a founder decision."""
    u = _admin(ctx, user_id)
    if u.status in ("offboarded", "pending_approval"):
        raise Conflict("This person is not currently employed")
    eff = _effective(body.effective_date, u)
    p = _profile(ctx, u.id)
    done = []
    if body.designation is not None and body.designation.strip() != (u.designation or ""):
        ev.record(ctx.db, u.id, "promoted", actor_id=ctx.user.id, effective=eff, frm={"designation": u.designation, "job_level": p.job_level},
                  to={"designation": body.designation.strip(), "job_level": body.job_level or p.job_level}, note=body.note)
        u.designation = body.designation.strip()
        done.append("designation")
        if body.job_level is not None:
            p.job_level = body.job_level
            done.append("job_level")
    elif body.job_level is not None and body.job_level != (p.job_level or ""):
        ev.record(ctx.db, u.id, "promoted", actor_id=ctx.user.id, effective=eff, frm={"designation": u.designation, "job_level": p.job_level},
                  to={"designation": u.designation, "job_level": body.job_level}, note=body.note)
        p.job_level = body.job_level
        done.append("job_level")
    if body.role is not None and body.role != u.role:
        if ctx.role != "founder":
            raise Forbidden("Only a founder can change someone's role")
        if u.role == "founder":
            raise Forbidden("A founder's role is changed from the employee record")
        _check_role_grant(ctx, body.role)
        ev.record(ctx.db, u.id, "role_changed", actor_id=ctx.user.id, effective=eff, frm={"role": u.role}, to={"role": body.role}, note=body.note)
        u.role = body.role
        ctx.db.flush()
        release_from_all_teams(ctx.db, u) if body.role == "employee" else None   # a demoted manager stops managing teams
        done.append("role")
    if not done:
        raise AppError("Nothing changed: give a new title, job level or role")
    u.session_version = (u.session_version or 0) + 1 if "role" in done else u.session_version
    audit(ctx, "employee.promoted", "user", u.id, {"fields": done})
    notify(ctx.db, [u.id], "Your role was updated", body.designation or "Your job details changed", "employee", "/profile")
    ctx.db.commit()
    return history(u.id, ctx)


class TransferIn(BaseModel):
    effective_date: date | None = None
    department_id: int | None = None
    branch_id: int | None = None
    manager_id: int | None = None
    note: str | None = Field(None, max_length=1000)
    clear_manager: bool = False

    @model_validator(mode="after")
    def _some(self):
        if self.department_id is None and self.branch_id is None and self.manager_id is None and not self.clear_manager:
            raise ValueError("Choose a department, branch or reporting manager to change")
        return self


@router.post("/employees/{user_id}/lifecycle/transfer")
def transfer(user_id: int, body: TransferIn, ctx: Ctx = Depends(get_ctx)):
    """Move someone to another department, branch and/or reporting manager. One history entry per thing that changed."""
    u = _admin(ctx, user_id)
    if u.status in ("offboarded", "pending_approval"):
        raise Conflict("This person is not currently employed")
    eff = _effective(body.effective_date, u)
    new_branch = body.branch_id if body.branch_id is not None else u.branch_id
    new_manager = None if body.clear_manager else (body.manager_id if body.manager_id is not None else u.manager_id)
    if body.branch_id is not None and body.branch_id != u.branch_id:
        _check_branch_change(ctx, body.branch_id)
        if u.role not in ("employee", "manager", "hr"):
            raise AppError("Founders and board members are company-wide")
    if body.manager_id == u.id:
        raise AppError("An employee cannot report to themselves")
    _validate_refs(ctx, body.department_id if body.department_id != u.department_id else None, new_manager if new_manager != u.manager_id or new_branch != u.branch_id else None,
                   u.id, branch_id=new_branch)
    changed = []
    if body.department_id is not None and body.department_id != u.department_id:
        ev.record(ctx.db, u.id, "department_changed", actor_id=ctx.user.id, effective=eff, frm=_ref(ctx.db.get(Department, u.department_id)) if u.department_id else None,
                  to=_ref(ctx.db.get(Department, body.department_id)), note=body.note)
        u.department_id = body.department_id
        changed.append("department")
    if body.branch_id is not None and body.branch_id != u.branch_id:
        ev.record(ctx.db, u.id, "branch_changed", actor_id=ctx.user.id, effective=eff, frm=_ref(ctx.db.get(Branch, u.branch_id)) if u.branch_id else None,
                  to=_ref(ctx.db.get(Branch, body.branch_id)), note=body.note)
        u.branch_id = body.branch_id
        changed.append("branch")
    if (body.manager_id is not None or body.clear_manager) and new_manager != u.manager_id:
        ev.record(ctx.db, u.id, "manager_changed", actor_id=ctx.user.id, effective=eff, frm=_ref(ctx.db.get(User, u.manager_id)) if u.manager_id else None,
                  to=_ref(ctx.db.get(User, new_manager)) if new_manager else None, note=body.note)
        u.manager_id = new_manager
        changed.append("manager")
    if not changed:
        raise AppError("Nothing changed: the person is already there")
    ctx.db.flush()
    if "branch" in changed:
        release_if_branch_mismatch(ctx.db, u)
    audit(ctx, "employee.transferred", "user", u.id, {"changed": changed})
    notify(ctx.db, [x for x in {u.id, u.manager_id} if x and x != ctx.user.id], "Employee moved", f"{u.full_name}: {', '.join(changed)} changed", "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return history(u.id, ctx)


# ================================================================== probation and confirmation

class ProbationIn(BaseModel):
    end_date: date
    note: str | None = Field(None, max_length=1000)


class ConfirmIn(BaseModel):
    effective_date: date | None = None
    note: str | None = Field(None, max_length=1000)


@router.post("/employees/{user_id}/lifecycle/probation")
def set_probation(user_id: int, body: ProbationIn, ctx: Ctx = Depends(get_ctx)):
    """Set the probation end date, or extend it."""
    u = _admin(ctx, user_id)
    if u.status in ("offboarded", "pending_approval"):
        raise Conflict("This person is not currently employed")
    p = _profile(ctx, u.id)
    if p.confirmation_date:
        raise Conflict("This person is already confirmed")
    if u.hire_date and body.end_date < u.hire_date:
        raise AppError(f"The probation cannot end before the joining date ({u.hire_date.isoformat()})", status_code=422)
    if p.probation_end_date == body.end_date:
        raise AppError("The probation already ends on this date")
    ev.record(ctx.db, u.id, "probation_set", actor_id=ctx.user.id, frm={"end_date": p.probation_end_date.isoformat() if p.probation_end_date else None},
              to={"end_date": body.end_date.isoformat()}, note=body.note)
    p.probation_end_date = body.end_date
    audit(ctx, "employee.probation_set", "user", u.id, {"end_date": body.end_date.isoformat()})
    notify(ctx.db, [x for x in {u.id, u.manager_id} if x and x != ctx.user.id], "Probation updated", f"{u.full_name}: probation ends {body.end_date}", "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return history(u.id, ctx)


@router.post("/employees/{user_id}/lifecycle/confirmation")
def confirm(user_id: int, body: ConfirmIn, ctx: Ctx = Depends(get_ctx)):
    u = _admin(ctx, user_id)
    if u.status in ("offboarded", "pending_approval", "suspended"):
        raise Conflict("This person cannot be confirmed right now")
    eff = _effective(body.effective_date, u)
    p = _profile(ctx, u.id)
    if p.confirmation_date:
        raise Conflict("This person is already confirmed")
    ev.record(ctx.db, u.id, "confirmed", actor_id=ctx.user.id, effective=eff, frm={"probation_end_date": p.probation_end_date.isoformat() if p.probation_end_date else None},
              to={"confirmation_date": eff.isoformat()}, note=body.note)
    p.confirmation_date = eff
    audit(ctx, "employee.confirmed", "user", u.id)
    notify(ctx.db, [u.id], "You have been confirmed", "Your probation is complete and your employment is confirmed.", "employee", "/profile")
    ctx.db.commit()
    return history(u.id, ctx)


# ================================================================== suspension

class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    until: date | None = None


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=1000)


def _guard_last_founder(ctx: Ctx, u: User) -> None:
    if u.role == "founder":
        if ctx.role != "founder":
            raise Forbidden("Only a founder can do this to a founder")
        if (ctx.db.scalar(select(func.count(User.id)).where(User.role == "founder", User.is_active.is_(True))) or 0) <= 1:
            raise AppError("A company must keep at least one active founder")


@router.post("/employees/{user_id}/lifecycle/suspend")
def suspend(user_id: int, body: SuspendIn, ctx: Ctx = Depends(get_ctx)):
    """Block sign-in immediately (every open session ends) while keeping the person's record, work and team membership."""
    u = _admin(ctx, user_id)
    if u.id == ctx.user.id:
        raise AppError("You cannot suspend yourself")
    if u.status not in ("active", "onboarding"):
        raise Conflict(f"A person who is {u.status.replace('_', ' ')} cannot be suspended")
    if body.until and body.until <= _today():
        raise AppError("The suspension must end in the future", status_code=422)
    _guard_last_founder(ctx, u)
    ev.record(ctx.db, u.id, "suspended", actor_id=ctx.user.id, frm={"status": u.status}, to={"until": body.until.isoformat() if body.until else None}, note=body.reason)
    u.status, u.is_active = "suspended", False
    u.session_version = (u.session_version or 0) + 1
    audit(ctx, "employee.suspended", "user", u.id)
    notify(ctx.db, [x for x in {u.manager_id} if x and x != ctx.user.id], "Employee suspended", f"{u.full_name} was suspended", "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return history(u.id, ctx)


@router.post("/employees/{user_id}/lifecycle/reinstate")
def reinstate(user_id: int, body: NoteIn, ctx: Ctx = Depends(get_ctx)):
    u = _admin(ctx, user_id)
    if u.status != "suspended":
        raise Conflict("This person is not suspended")
    _plan_limit(ctx)
    prev = _last_event(ctx, u.id, "suspended")
    ev.record(ctx.db, u.id, "reinstated", actor_id=ctx.user.id, frm={"status": "suspended"}, to={"status": (prev.from_value or {}).get("status", "active") if prev else "active"}, note=body.note)
    u.status, u.is_active = (prev.from_value or {}).get("status", "active") if prev else "active", True
    audit(ctx, "employee.reinstated", "user", u.id)
    ctx.db.commit()
    return history(u.id, ctx)


# ================================================================== resignation, leaving, coming back

class ResignIn(BaseModel):
    last_working_date: date
    reason: str | None = Field(None, max_length=1000)


@router.post("/employees/{user_id}/lifecycle/resignation")
def resign(user_id: int, body: ResignIn, ctx: Ctx = Depends(get_ctx)):
    """You can submit your own resignation; HR / founders can record one on someone's behalf."""
    u = _get_user(ctx, user_id)
    own = u.id == ctx.user.id
    if not own:
        u = _admin(ctx, user_id)
    if u.status not in ("active", "onboarding", "suspended"):
        raise Conflict("There is nothing to resign from")
    if body.last_working_date < _today():
        raise AppError("The last working day cannot be in the past", status_code=422)
    last = _last_event(ctx, u.id, "resignation_submitted", "resignation_withdrawn")
    if last is not None and last.kind == "resignation_submitted":
        raise Conflict("A resignation is already on record; withdraw it first to change the date")
    p = _profile(ctx, u.id)
    notice = p.notice_period_days
    short = notice is not None and (body.last_working_date - _today()).days < notice
    ev.record(ctx.db, u.id, "resignation_submitted", actor_id=ctx.user.id, frm={"last_working_date": p.last_working_date.isoformat() if p.last_working_date else None},
              to={"last_working_date": body.last_working_date.isoformat(), "notice_period_days": notice, "shorter_than_notice": bool(short)}, note=body.reason)
    p.last_working_date = body.last_working_date
    audit(ctx, "employee.resignation_submitted", "user", u.id, {"last_working_date": body.last_working_date.isoformat()})
    hr = [x.id for x in ctx.db.scalars(select(User).where(User.is_active.is_(True), User.role.in_(("hr", "founder")), User.id != ctx.user.id)) if x.branch_id in (None, u.branch_id) or x.role == "founder"]
    notify(ctx.db, sorted({*(hr), *([u.manager_id] if u.manager_id else [])} - {ctx.user.id}), "Resignation", f"{u.full_name}: last working day {body.last_working_date}", "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return {**history(u.id, ctx), "warning": f"This is shorter than the {notice}-day notice period." if short else None}


@router.post("/employees/{user_id}/lifecycle/resignation/withdraw")
def withdraw_resignation(user_id: int, body: NoteIn, ctx: Ctx = Depends(get_ctx)):
    u = _get_user(ctx, user_id)
    if u.id != ctx.user.id:
        u = _admin(ctx, user_id)
    last = _last_event(ctx, u.id, "resignation_submitted", "resignation_withdrawn")
    if last is None or last.kind != "resignation_submitted" or u.status == "offboarded":
        raise Conflict("There is no open resignation")
    p = _profile(ctx, u.id)
    ev.record(ctx.db, u.id, "resignation_withdrawn", actor_id=ctx.user.id, frm={"last_working_date": p.last_working_date.isoformat() if p.last_working_date else None}, note=body.note)
    p.last_working_date = None
    audit(ctx, "employee.resignation_withdrawn", "user", u.id)
    notify(ctx.db, [x for x in {u.manager_id} if x and x != ctx.user.id], "Resignation withdrawn", u.full_name, "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return history(u.id, ctx)


class ReactivateIn(BaseModel):
    note: str | None = Field(None, max_length=1000)
    hire_date: date | None = None


@router.post("/employees/{user_id}/lifecycle/reactivate")
def reactivate(user_id: int, body: ReactivateIn, ctx: Ctx = Depends(get_ctx)):
    """Bring a former employee back with their history intact. Their old sessions stay dead; HR resets the password if needed."""
    u = _admin(ctx, user_id)
    if u.status != "offboarded":
        raise Conflict("Only a former employee can be reactivated")
    if body.hire_date and body.hire_date > _today():
        raise AppError("The new joining date cannot be in the future", status_code=422)
    _plan_limit(ctx)
    ev.record(ctx.db, u.id, "reactivated", actor_id=ctx.user.id, effective=body.hire_date, frm={"offboarded_at": u.offboarded_at.date().isoformat() if u.offboarded_at else None},
              to={"hire_date": (body.hire_date or u.hire_date).isoformat() if (body.hire_date or u.hire_date) else None}, note=body.note)
    u.status, u.is_active, u.offboarded_at = "active", True, None
    if body.hire_date:
        u.hire_date = body.hire_date
    u.session_version = (u.session_version or 0) + 1
    p = _profile(ctx, u.id)
    p.last_working_date = None
    ensure_balances(ctx.db, u, _today().year)
    audit(ctx, "employee.reactivated", "user", u.id)
    notify(ctx.db, [x for x in {u.manager_id} if x and x != ctx.user.id], "Former employee returned", u.full_name, "employee", f"/employees/{u.id}")
    ctx.db.commit()
    return history(u.id, ctx)


# ================================================================== worklists and feed

@router.get("/lifecycle/due")
def due(days: int = 30, ctx: Ctx = Depends(staff)):
    """What needs HR's attention: probations ending, upcoming and overdue departures, exit clearance still open."""
    days = max(1, min(days, 180))
    today = _today()
    horizon = today + timedelta(days=days)
    base = select(User, EmployeeProfile).join(EmployeeProfile, EmployeeProfile.user_id == User.id).where(user_scope(ctx), User.role.in_(("employee", "manager", "hr")))
    probation = [{"user_id": u.id, "name": u.full_name, "date": p.probation_end_date, "overdue": p.probation_end_date < today}
                 for u, p in ctx.db.execute(base.where(User.is_active.is_(True), EmployeeProfile.confirmation_date.is_(None), EmployeeProfile.probation_end_date.is_not(None),
                                                       EmployeeProfile.probation_end_date <= horizon).order_by(EmployeeProfile.probation_end_date))]
    leaving = [{"user_id": u.id, "name": u.full_name, "date": p.last_working_date, "overdue": p.last_working_date < today}
               for u, p in ctx.db.execute(base.where(User.status.in_(("active", "onboarding", "suspended")), EmployeeProfile.last_working_date.is_not(None),
                                                     EmployeeProfile.last_working_date <= horizon).order_by(EmployeeProfile.last_working_date))]
    open_clearance = []
    for u in ctx.db.scalars(select(User).where(user_scope(ctx), User.status == "offboarded")):
        items = ctx.db.scalars(select(ChecklistItem).where(ChecklistItem.user_id == u.id, ChecklistItem.kind == "offboarding")).all()
        if items and not all(i.done for i in items):
            open_clearance.append({"user_id": u.id, "name": u.full_name, "done": sum(1 for i in items if i.done), "total": len(items), "date": u.offboarded_at.date() if u.offboarded_at else None})
    return {"days": days, "probation": probation, "leaving": leaving, "exit_clearance": open_clearance}


@router.get("/lifecycle/events")
def feed(kind: str | None = None, days: int = 90, params: PageParams = Depends(), ctx: Ctx = Depends(staff)):
    stmt = select(EmployeeEvent).join(User, User.id == EmployeeEvent.user_id).where(EmployeeEvent.effective_date >= _today() - timedelta(days=max(1, min(days, 3650))))
    if ctx.role == "hr":  # HR never sees founders' or board members' history
        stmt = stmt.where(user_scope(ctx), User.role.in_(("employee", "manager", "hr")))
    if kind:
        stmt = stmt.where(EmployeeEvent.kind == kind)
    stmt = stmt.order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc())
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    return paginate(ctx.db, stmt, params, lambda e: {**ser_event(e, names), "employee": names.get(e.user_id)})


# ================================================================== org chart

@router.get("/org/chart")
def org_chart(branch_id: int | None = None, department_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    """The reporting tree of everyone currently working here. People whose manager is outside the filter appear as roots."""
    if ctx.role == "board_member":
        raise Forbidden("Board members have no access to employee data")
    q = select(User).where(User.is_active.is_(True), User.role.in_(("employee", "manager", "hr", "founder")), User.status != "pending_approval")
    if branch_id:
        q = q.where(User.branch_id == branch_id)
    if department_id:
        q = q.where(User.department_id == department_id)
    users = list(ctx.db.scalars(q.order_by(User.full_name)))
    from app.modules.employees.router import _can_view  # the same rule that decides whether GET /employees/{id} answers
    depts = {d.id: d.name for d in ctx.db.scalars(select(Department))}
    branches = {b.id: b.name for b in ctx.db.scalars(select(Branch))}
    nodes = {u.id: {"id": u.id, "name": u.full_name, "designation": u.designation, "role": u.role, "department": depts.get(u.department_id), "branch": branches.get(u.branch_id),
                    "avatar_v": u.avatar_name, "can_open": _can_view(ctx, u), "children": []} for u in users}
    roots = []
    for u in users:
        parent = nodes.get(u.manager_id) if u.manager_id else None
        (parent["children"] if parent is not None and u.manager_id != u.id else roots).append(nodes[u.id])

    def count(n: dict, seen: set) -> int:
        seen.add(n["id"])
        n["reports"] = sum(1 + count(c, seen) for c in n["children"] if c["id"] not in seen)
        return n["reports"]

    for r in roots:
        count(r, set())
    return {"roots": roots, "total": len(users)}
