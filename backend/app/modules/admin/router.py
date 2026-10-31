from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.common import PageParams, audit, paginate
from app.core.errors import AppError
from app.db.tenant_models import AuditLog, Project, Setting, Task, User
from app.deps import Ctx, get_ctx, require_roles

router = APIRouter(prefix="/admin", tags=["administration"])

# key -> (validator, description)
def _valid_tz(v: str) -> bool:
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(v)
        return True
    except Exception:  # noqa: BLE001 - unknown name, bad key, or missing tz database
        return False


SETTING_RULES = {
    "standard_work_hours": (lambda v: 1 <= float(v) <= 16, "Standard daily working hours (overtime beyond this)"),
    "company_timezone": (lambda v: _valid_tz(v), "Default IANA timezone for attendance (a branch's own timezone wins), e.g. Asia/Kolkata"),
    "payroll_currency": (lambda v: len(v) == 3 and v.isalpha(), "Default payroll currency (ISO 4217 code, e.g. EUR)"),
    "payroll_attendance_basis": (lambda v: v in ("ignore", "attendance"), "ignore = pay every working day except unpaid leave; attendance = pay only days worked or on paid leave"),
    "payroll_overtime_multiplier": (lambda v: 0 <= float(v) <= 5, "Overtime pay multiplier on the hourly rate (0 = overtime is not paid)"),
    "allow_wfh": (lambda v: v.lower() in ("true", "false"), "Allow work-from-home check-ins (true/false)"),
}


class SettingIn(BaseModel):
    value: str = Field(max_length=200)


@router.get("/audit-logs")
def audit_logs(action: str | None = None, actor_id: int | None = None, start: date | None = None, end: date | None = None,
               params: PageParams = Depends(), ctx: Ctx = Depends(require_roles("founder", "hr"))):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if start:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start, datetime.min.time()))
    if end:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    if ctx.role == "hr" and ctx.user.branch_id is not None:  # branch HR: only events caused by people of their branch
        stmt = stmt.where(AuditLog.actor_id.in_(select(User.id).where(User.branch_id == ctx.user.branch_id)))
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    return paginate(ctx.db, stmt, params, lambda a: {
        "id": a.id, "actor_id": a.actor_id, "actor_name": names.get(a.actor_id), "action": a.action,
        "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail, "ip": a.ip, "created_at": a.created_at})


@router.get("/settings")
def get_settings_(ctx: Ctx = Depends(get_ctx)):
    rows = {s.key: s.value for s in ctx.db.scalars(select(Setting))}
    return {"items": [{"key": k, "value": rows.get(k, ""), "description": d} for k, (_, d) in SETTING_RULES.items()]}


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, ctx: Ctx = Depends(require_roles("founder"))):
    if key not in SETTING_RULES:
        raise AppError("Unknown setting")
    try:
        ok = SETTING_RULES[key][0](body.value)
    except ValueError:
        ok = False
    if not ok:
        raise AppError("Invalid value for this setting")
    row = ctx.db.get(Setting, key)
    if row:
        row.value = body.value
    else:
        ctx.db.add(Setting(key=key, value=body.value))
    audit(ctx, "settings.updated", "setting", None, {"key": key, "value": body.value})
    ctx.db.commit()
    return {"key": key, "value": body.value}


@router.get("/usage")
def usage(ctx: Ctx = Depends(require_roles("founder", "hr"))):
    return {
        "users": ctx.db.scalar(select(func.count(User.id))),
        "active_users": ctx.db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))),
        "projects": ctx.db.scalar(select(func.count(Project.id))),
        "tasks": ctx.db.scalar(select(func.count(Task.id))),
        "audit_events": ctx.db.scalar(select(func.count(AuditLog.id))),
    }
