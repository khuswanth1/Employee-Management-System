from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access import require_permission, user_scope
from app.common import PageParams, audit, get_setting, paginate
from app.core.errors import AppError, Conflict, Forbidden
from app.db.base import as_utc, utcnow
from app.db.tenant_models import Attendance, AttendanceBreak, User
from app.deps import Ctx, get_ctx
from app.modules.attendance import engine as eng
from app.modules.attendance import service as svc
from app.modules.webhooks.service import emit

router = APIRouter(prefix="/attendance", tags=["attendance"])


def metrics(a: Attendance, std_hours: float) -> dict:
    """Simple UTC calculation kept for callers that have no user/branch context (see engine.compute for the real rules)."""
    end = as_utc(a.check_out) or utcnow()
    total = (end - as_utc(a.check_in)).total_seconds()
    brk = sum(((as_utc(b.end) or end) - as_utc(b.start)).total_seconds() for b in a.breaks)
    worked = max(0.0, total - brk) / 3600
    return {"worked_hours": round(worked, 2), "break_minutes": round(brk / 60), "overtime_hours": round(max(0.0, worked - std_hours), 2)}


def _std(ctx: Ctx) -> float:
    try:
        return float(get_setting(ctx.db, "standard_work_hours", "8"))
    except ValueError:
        return 8.0


class CheckInIn(BaseModel):
    work_mode: Literal["office", "wfh"] = "office"
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


def _my_open(ctx: Ctx) -> Attendance | None:
    return svc.open_session(ctx.db, ctx.user.id)


def _close_if_forgotten(ctx: Ctx, res: svc.Resolver, a: Attendance) -> bool:
    """A session left open for far too long is closed automatically; returns True if that happened."""
    if svc.stale(a, ctx.user, res, utcnow()):
        svc.auto_close(a, ctx.user, res)
        audit(ctx, "attendance.auto_closed", "attendance", a.id, {"work_date": a.work_date.isoformat()})
        return True
    return False


def _geofence_check(res: svc.Resolver, user: User, body: CheckInIn) -> None:
    b = res.branch_of(user)
    if body.work_mode == "wfh":
        if not res.allow_wfh:
            raise Forbidden("Working from home is not enabled for this company")
        return
    if b is None or not b.geo_required or b.geo_lat is None or b.geo_lng is None or not b.geo_radius_m:
        return
    if body.lat is None or body.lng is None:
        raise AppError("Your location is needed to check in at this branch. Allow location access and try again.", status_code=422, code="location_required")
    dist = eng.haversine_m(body.lat, body.lng, b.geo_lat, b.geo_lng)
    if dist > b.geo_radius_m:
        raise Forbidden(f"You are about {int(dist)} m from {b.name}; check in within {b.geo_radius_m} m, or choose work from home.")


@router.get("/today")
def today(ctx: Ctx = Depends(get_ctx)):
    res = svc.Resolver(ctx.db)
    now = utcnow()
    a = _my_open(ctx)
    cal = res.calendar(ctx.user)
    if a is not None and _close_if_forgotten(ctx, res, a):
        ctx.db.commit()  # a session nobody closed must not look live: the page would offer Start break / Check out that the server then refuses
        a = None
    if a is None:
        wd = eng.work_date_for(now, res.rule(ctx.user.shift_id), cal.tz)
        a = ctx.db.scalar(select(Attendance).where(Attendance.user_id == ctx.user.id, Attendance.work_date == wd))
    shift = res.shift_for(ctx.user.shift_id)
    return {
        "record": svc.view(a, ctx.user, res, ctx.user.full_name, now) if a else None,
        "timezone": str(cal.tz), "allow_wfh": res.allow_wfh,
        "geofence_required": bool((b := res.branch_of(ctx.user)) and b.geo_required and b.geo_radius_m),
        "shift": {"id": shift.id, "name": shift.name, "start": shift.start_time, "end": shift.end_time, "grace_minutes": shift.grace_minutes,
                  "required_hours": shift.required_hours} if shift else None,
    }


@router.post("/check-in", status_code=201)
def check_in(body: CheckInIn | None = None, ctx: Ctx = Depends(get_ctx)):
    body = body or CheckInIn()
    res = svc.Resolver(ctx.db)
    user, now = ctx.user, utcnow()
    open_ = _my_open(ctx)
    if open_ is not None and not _close_if_forgotten(ctx, res, open_):
        raise Conflict("You are already checked in")
    cal = res.calendar(user)
    wd = eng.work_date_for(now, res.rule(user.shift_id), cal.tz)
    if ctx.db.scalar(select(Attendance.id).where(Attendance.user_id == user.id, Attendance.work_date == wd)):
        ctx.db.commit()  # keep an automatic close made above
        raise Conflict("You have already worked this day. If the times are wrong, request a correction.")
    _geofence_check(res, user, body)
    a = Attendance(user_id=user.id, work_date=wd, check_in=now, work_mode=body.work_mode, shift_id=user.shift_id,
                   check_in_lat=body.lat if body.work_mode == "office" else None, check_in_lng=body.lng if body.work_mode == "office" else None)
    ctx.db.add(a)
    emit(ctx.db, "attendance.checked_in", {"user_id": user.id, "at": now.isoformat(), "work_mode": body.work_mode})
    ctx.db.commit()
    return svc.view(a, user, res, user.full_name, now)


@router.post("/check-out")
def check_out(ctx: Ctx = Depends(get_ctx)):
    res = svc.Resolver(ctx.db)
    a = _my_open(ctx)
    now = utcnow()
    if a is None:
        wd = eng.work_date_for(now, res.rule(ctx.user.shift_id), res.calendar(ctx.user).tz)
        if ctx.db.scalar(select(Attendance.id).where(Attendance.user_id == ctx.user.id, Attendance.work_date == wd, Attendance.check_out.is_not(None))):
            raise Conflict("You have already checked out for this work day")
        raise AppError("You have not checked in")
    if _close_if_forgotten(ctx, res, a):
        ctx.db.commit()
        raise Conflict("Your previous session was never closed, so it was ended automatically. Request a correction to set the real times.")
    if (b := next((b for b in a.breaks if b.end is None), None)):
        b.end = now
    a.check_out = now
    svc.finalize(a, ctx.user, res)
    emit(ctx.db, "attendance.checked_out", {"user_id": ctx.user.id, "at": now.isoformat(), "status": a.status})
    ctx.db.commit()
    return svc.view(a, ctx.user, res, ctx.user.full_name, now)


@router.post("/break/start")
def break_start(ctx: Ctx = Depends(get_ctx)):
    res = svc.Resolver(ctx.db)
    a = _my_open(ctx)
    if a is None:
        raise AppError("You must be checked in to start a break")
    if _close_if_forgotten(ctx, res, a):
        ctx.db.commit()
        raise Conflict("Your previous session was never closed, so it was ended automatically. Request a correction to set the real times.")
    if any(b.end is None for b in a.breaks):
        raise Conflict("A break is already in progress")
    a.breaks.append(AttendanceBreak(start=utcnow()))
    ctx.db.commit()
    return svc.view(a, ctx.user, res, ctx.user.full_name)


@router.post("/break/end")
def break_end(ctx: Ctx = Depends(get_ctx)):
    res = svc.Resolver(ctx.db)
    a = _my_open(ctx)
    if a is not None and _close_if_forgotten(ctx, res, a):
        ctx.db.commit()
        raise Conflict("Your previous session was never closed, so it was ended automatically. Request a correction to set the real times.")
    b = next((b for b in a.breaks if b.end is None), None) if a else None
    if b is None:
        raise AppError("No break in progress")
    b.end = utcnow()
    ctx.db.commit()
    return svc.view(a, ctx.user, res, ctx.user.full_name)


@router.get("/mine")
def mine(start: date | None = None, end: date | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    start = start or utcnow().date() - timedelta(days=30)
    stmt = select(Attendance).where(Attendance.user_id == ctx.user.id, Attendance.work_date >= start).order_by(Attendance.work_date.desc())
    if end:
        stmt = stmt.where(Attendance.work_date <= end)
    res = svc.Resolver(ctx.db)
    return paginate(ctx.db, stmt, params, lambda a: svc.view(a, ctx.user, res, ctx.user.full_name))


def scoped_attendance(ctx: Ctx, start: date, end: date, user_id: int | None = None):
    stmt = select(Attendance).where(Attendance.work_date >= start, Attendance.work_date <= end).order_by(Attendance.work_date.desc(), Attendance.user_id)
    if ctx.role != "founder":
        stmt = stmt.join(User, User.id == Attendance.user_id).where(user_scope(ctx))
    if user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    return stmt


reports_view = require_permission("reports.view", "manager", "hr", "founder")


@router.get("")
def team(start: date | None = None, end: date | None = None, user_id: int | None = None, status: str | None = None,
         params: PageParams = Depends(), ctx: Ctx = Depends(reports_view)):
    end = end or utcnow().date()
    start = start or end - timedelta(days=30)
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    res = svc.Resolver(ctx.db)
    stmt = scoped_attendance(ctx, start, end, user_id)
    if status:
        stmt = stmt.where(Attendance.status == status)
    return paginate(ctx.db, stmt, params, lambda a: svc.view(a, users.get(a.user_id), res, users[a.user_id].full_name if a.user_id in users else None))


@router.get("/summary")
def summary(start: date | None = None, end: date | None = None, ctx: Ctx = Depends(reports_view)):
    end = end or utcnow().date()
    start = start or end - timedelta(days=30)
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    res = svc.Resolver(ctx.db)
    agg: dict[int, dict] = {}
    for a in ctx.db.scalars(scoped_attendance(ctx, start, end)):
        v = svc.view(a, users.get(a.user_id), res)
        s = agg.setdefault(a.user_id, {
            "user_id": a.user_id, "user_name": users[a.user_id].full_name if a.user_id in users else None, "days_present": 0,
            "worked_hours": 0.0, "overtime_hours": 0.0, "late_days": 0, "late_minutes": 0, "early_departures": 0, "half_days": 0,
            "short_days": 0, "weekend_days": 0, "holiday_days": 0, "wfh_days": 0, "auto_closed": 0})
        s["days_present"] += 1
        s["worked_hours"] = round(s["worked_hours"] + v["worked_hours"], 2)
        s["overtime_hours"] = round(s["overtime_hours"] + v["overtime_hours"], 2)
        s["late_days"] += 1 if v["late_minutes"] else 0
        s["late_minutes"] += v["late_minutes"]
        s["early_departures"] += 1 if v["early_minutes"] else 0
        s["half_days"] += v["status"] == "half_day"
        s["short_days"] += v["status"] == "short_day"
        s["weekend_days"] += v["day_type"] == "weekend"
        s["holiday_days"] += v["day_type"] == "holiday"
        s["wfh_days"] += v["work_mode"] == "wfh"
        s["auto_closed"] += bool(v["auto_closed"])
    return {"items": sorted(agg.values(), key=lambda x: x["user_name"] or "")}
