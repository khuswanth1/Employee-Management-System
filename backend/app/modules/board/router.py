"""Board members: founder-managed profiles and aggregate-only company analytics.

Board members never see individual employee records. Everything they can read here is an aggregate
(counts and rates), and there is no financial data model in WorkSphere, so no financial summary is offered.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import utcnow
from app.access import BOARD_PERMISSIONS
from app.common import audit, to_csv
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.security import hash_password, validate_password_strength
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import (
    Attendance, AuditLog, Branch, BoardProfile, Department, LeaveRequest, Message, Notification, Project, Task, User,
)
from app.deps import Ctx, get_ctx, require_roles

router = APIRouter(prefix="/board", tags=["board"])
founder_only = require_roles("founder")


def _perms(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    unknown = set(v) - set(BOARD_PERMISSIONS)
    if unknown:
        raise ValueError(f"Unknown permission(s): {', '.join(sorted(unknown))}")
    return sorted(set(v))


class BoardCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(max_length=200)
    designation: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)
    responsibilities: str | None = Field(None, max_length=4000)
    term_start: date | None = None
    permissions: list[str] = Field(default_factory=lambda: sorted(BOARD_PERMISSIONS))

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        validate_password_strength(v)
        return v

    _perm = field_validator("permissions")(classmethod(lambda cls, v: _perms(v)))


class BoardUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)
    responsibilities: str | None = Field(None, max_length=4000)
    term_start: date | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None

    _perm = field_validator("permissions")(classmethod(lambda cls, v: _perms(v)))


def _profile(ctx: Ctx, u: User) -> BoardProfile:
    p = ctx.db.get(BoardProfile, u.id)
    if p is None:
        p = BoardProfile(user_id=u.id, permissions=sorted(BOARD_PERMISSIONS))
        ctx.db.add(p)
        ctx.db.flush()
    return p


def ser_member(ctx: Ctx, u: User, full: bool = True) -> dict:
    p = ctx.db.get(BoardProfile, u.id)
    d = {"id": u.id, "full_name": u.full_name, "designation": u.designation, "avatar_v": u.avatar_name, "is_active": u.is_active,
         "responsibilities": p.responsibilities if p else None, "term_start": p.term_start if p else None}
    if full:
        d.update(email=u.email, phone=u.phone, employee_code=u.employee_code,
                 permissions=(p.permissions if p and p.permissions is not None else sorted(BOARD_PERMISSIONS)))
    return d


def _get_member(ctx: Ctx, uid: int) -> User:
    u = ctx.db.get(User, uid)
    if u is None or u.role != "board_member":
        raise NotFound("Board member not found")
    return u


@router.get("/permissions-catalog")
def catalog(ctx: Ctx = Depends(founder_only)):
    return {"items": [{"key": k, "description": d} for k, d in BOARD_PERMISSIONS.items()]}


@router.get("/members")
def list_members(ctx: Ctx = Depends(require_roles("founder", "board_member"))):
    rows = ctx.db.scalars(select(User).where(User.role == "board_member").order_by(User.full_name))
    return {"items": [ser_member(ctx, u, full=ctx.role == "founder") for u in rows]}


@router.post("/members", status_code=201)
def create_member(body: BoardCreate, ctx: Ctx = Depends(founder_only)):
    with platform_session() as pdb:
        max_users = pdb.get(Company, ctx.company_id).max_users
    if (ctx.db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0) >= max_users:
        raise AppError("User limit reached for this company plan", status_code=402, code="plan_limit")
    if ctx.db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise Conflict("A user with this email already exists")
    u = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role="board_member",
             status="active", designation=body.designation, phone=body.phone, hire_date=utcnow().date())
    ctx.db.add(u)
    ctx.db.flush()
    u.employee_code = f"BRD-{u.id:04d}"
    ctx.db.add(BoardProfile(user_id=u.id, responsibilities=body.responsibilities, term_start=body.term_start, permissions=body.permissions))
    audit(ctx, "board.member_created", "user", u.id, {"permissions": body.permissions})
    ctx.db.commit()
    return ser_member(ctx, u)


@router.get("/members/{uid}")
def get_member(uid: int, ctx: Ctx = Depends(founder_only)):
    return ser_member(ctx, _get_member(ctx, uid))


@router.patch("/members/{uid}")
def update_member(uid: int, body: BoardUpdate, ctx: Ctx = Depends(founder_only)):
    u = _get_member(ctx, uid)
    p = _profile(ctx, u)
    data = body.model_dump(exclude_unset=True)
    for k in ("full_name", "is_active"):
        if k in data and data[k] is None:
            data.pop(k)
    for k in ("full_name", "designation", "phone"):
        if k in data:
            setattr(u, k, data[k].strip() if isinstance(data[k], str) else data[k])
    for k in ("responsibilities", "term_start", "permissions"):
        if k in data:
            setattr(p, k, data[k])
    if "is_active" in data:
        u.is_active = data["is_active"]
        u.status = "active" if u.is_active else "offboarded"
    audit(ctx, "board.member_updated", "user", u.id, {"fields": sorted(data), **({"permissions": data["permissions"]} if "permissions" in data else {})})
    ctx.db.commit()
    return ser_member(ctx, u)


@router.delete("/members/{uid}", status_code=204)
def delete_member(uid: int, ctx: Ctx = Depends(founder_only)):
    u = _get_member(ctx, uid)
    used = ctx.db.scalar(select(Message.id).where(Message.sender_id == u.id).limit(1)) or ctx.db.scalar(select(AuditLog.id).where(AuditLog.actor_id == u.id).limit(1))
    if used:
        raise Conflict("This board member has activity on record. Deactivate them instead.")
    name = u.full_name
    try:
        with ctx.db.begin_nested():
            ctx.db.query(Notification).filter(Notification.user_id == u.id).delete(synchronize_session=False)
            ctx.db.query(BoardProfile).filter(BoardProfile.user_id == u.id).delete(synchronize_session=False)
            ctx.db.delete(u)
            ctx.db.flush()
    except IntegrityError:
        raise Conflict("This board member has records and cannot be deleted. Deactivate them instead.")
    audit(ctx, "board.member_deleted", "user", uid, {"name": name})
    ctx.db.commit()


# ---- analytics (aggregates only) --------------------------------------------------------------------------

def _board_can(ctx: Ctx, key: str) -> None:
    if ctx.role == "founder":
        return
    if ctx.role != "board_member":
        raise Forbidden()
    p = ctx.db.get(BoardProfile, ctx.user.id)
    granted = p.permissions if p and p.permissions is not None else list(BOARD_PERMISSIONS)
    if key not in granted:
        raise Forbidden(f"Your board profile does not include '{key}'")


def _analytics(ctx: Ctx) -> dict:
    db, today = ctx.db, utcnow().date()
    staff = User.role != "board_member"
    active = (User.is_active.is_(True), staff)
    headcount = db.scalar(select(func.count(User.id)).where(*active)) or 0
    by_branch = [{"branch": n or "Unassigned", "count": c} for n, c in db.execute(
        select(Branch.name, func.count(User.id)).select_from(User).outerjoin(Branch, Branch.id == User.branch_id).where(*active).group_by(Branch.name))]
    by_dept = [{"department": n or "Unassigned", "count": c} for n, c in db.execute(
        select(Department.name, func.count(User.id)).select_from(User).outerjoin(Department, Department.id == User.department_id).where(*active).group_by(Department.name))]
    by_role = dict(db.execute(select(User.role, func.count(User.id)).where(*active).group_by(User.role)).all())
    since = today - timedelta(days=30)
    new_hires = db.scalar(select(func.count(User.id)).where(User.hire_date >= since, *active)) or 0
    present = db.scalar(select(func.count(Attendance.id)).where(Attendance.work_date == today)) or 0
    year_start = date(today.year, 1, 1)
    leave_days = db.scalar(select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(LeaveRequest.status == "approved", LeaveRequest.start_date >= year_start)) or 0
    pending_leave = db.scalar(select(func.count(LeaveRequest.id)).where(LeaveRequest.status == "pending")) or 0
    proj = dict(db.execute(select(Project.status, func.count(Project.id)).group_by(Project.status)).all())
    task = dict(db.execute(select(Task.status, func.count(Task.id)).group_by(Task.status)).all())
    total_tasks = sum(task.values())
    overdue = db.scalar(select(func.count(Task.id)).where(Task.status != "done", Task.due_date < today)) or 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headcount": headcount, "by_branch": by_branch, "by_department": by_dept, "by_role": by_role, "new_hires_30d": new_hires,
        "attendance_today": {"present": present, "headcount": headcount, "rate": round(100 * present / headcount) if headcount else 0},
        "leave": {"approved_days_ytd": float(leave_days), "pending_requests": pending_leave},
        "projects": proj, "tasks": {"by_status": task, "completion_rate": round(100 * task.get("done", 0) / total_tasks) if total_tasks else 0, "overdue": overdue},
        "financial": {"available": False, "reason": "WorkSphere has no financial data model, so no financial summary can be produced."},
    }


@router.get("/analytics")
def analytics(ctx: Ctx = Depends(get_ctx)):
    _board_can(ctx, "analytics.view")
    return _analytics(ctx)


@router.get("/reports/headcount.csv")
def headcount_report(ctx: Ctx = Depends(get_ctx)):
    """Strategic summary: active headcount by branch and department (no individual records)."""
    _board_can(ctx, "reports.view")
    rows = ctx.db.execute(
        select(Branch.name, Department.name, func.count(User.id)).select_from(User)
        .outerjoin(Branch, Branch.id == User.branch_id).outerjoin(Department, Department.id == User.department_id)
        .where(User.is_active.is_(True), User.role != "board_member").group_by(Branch.name, Department.name)
        .order_by(Branch.name, Department.name)).all()
    body = to_csv(["Branch", "Department", "Headcount"], [[b or "Unassigned", d or "Unassigned", n] for b, d, n in rows])
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="headcount-summary.csv"'})
