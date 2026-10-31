"""Attendance correction requests: an employee asks to fix a day's times, an approver in scope decides, and only an approval
changes the attendance record (which then carries source=correction and a full audit trail)."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access import has_permission, user_scope
from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import Attendance, AttendanceCorrection, User
from app.deps import Ctx, get_ctx
from app.modules.attendance import engine as eng
from app.modules.attendance import service as svc
from app.modules.notifications.service import notify

router = APIRouter(prefix="/attendance/corrections", tags=["attendance corrections"])
MAX_AGE_DAYS = 60
MAX_SESSION_HOURS = 24


class CorrectionIn(BaseModel):
    # Naive values (from a datetime-local input) are the employee's local wall-clock time; offsets are honoured.
    check_in: datetime
    check_out: datetime
    reason: str = Field(min_length=5, max_length=1000)


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=1000)


def ser(c: AttendanceCorrection, name: str | None = None, decider: str | None = None, tz: str | None = None) -> dict:
    return {"id": c.id, "user_id": c.user_id, "user_name": name, "work_date": c.work_date, "check_in": c.requested_check_in,
            "check_out": c.requested_check_out, "reason": c.reason, "status": c.status, "decided_by": c.decided_by, "decided_by_name": decider,
            "decided_at": c.decided_at, "decision_note": c.decision_note, "attendance_id": c.attendance_id, "created_at": c.created_at, "timezone": tz}


def approvers_of(ctx: Ctx, user: User) -> list[int]:
    """Who is told about a request: the line manager if any, else HR of the branch and the founders."""
    if user.manager_id:
        return [user.manager_id]
    q = select(User.id).where(User.is_active.is_(True), ((User.role == "hr") & ((User.branch_id == user.branch_id) | (User.branch_id.is_(None)))) | (User.role == "founder"))
    return [i for i in ctx.db.scalars(q) if i != user.id]


@router.post("", status_code=201)
def request_correction(body: CorrectionIn, ctx: Ctx = Depends(get_ctx)):
    res = svc.Resolver(ctx.db)
    user, now = ctx.user, utcnow()
    cal = res.calendar(user)
    cin, cout = svc.local_to_utc(body.check_in, cal.tz), svc.local_to_utc(body.check_out, cal.tz)
    if cout <= cin:
        raise AppError("Check-out must be after check-in")
    if cout - cin > timedelta(hours=MAX_SESSION_HOURS):
        raise AppError(f"A single session cannot be longer than {MAX_SESSION_HOURS} hours")
    if cout > now + timedelta(minutes=5):
        raise AppError("Times in the future cannot be requested")
    wd = eng.work_date_for(cin, res.rule(user.shift_id), cal.tz)
    if wd < (now.astimezone(cal.tz).date() - timedelta(days=MAX_AGE_DAYS)):
        raise AppError(f"Corrections can only be requested for the last {MAX_AGE_DAYS} days")
    if ctx.db.scalar(select(AttendanceCorrection.id).where(AttendanceCorrection.user_id == user.id, AttendanceCorrection.work_date == wd,
                                                           AttendanceCorrection.status == "pending")):
        raise Conflict("You already have a pending correction for this day")
    c = AttendanceCorrection(user_id=user.id, work_date=wd, requested_check_in=cin, requested_check_out=cout, reason=body.reason.strip())
    ctx.db.add(c)
    ctx.db.flush()
    notify(ctx.db, approvers_of(ctx, user), "Attendance correction requested", f"{user.full_name} asked to correct {wd.isoformat()}", "attendance", "/attendance/corrections")
    audit(ctx, "attendance.correction_requested", "attendance_correction", c.id, {"work_date": wd.isoformat()})
    ctx.db.commit()
    return ser(c, user.full_name, tz=str(cal.tz))


@router.get("/mine")
def mine(params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(AttendanceCorrection).where(AttendanceCorrection.user_id == ctx.user.id).order_by(AttendanceCorrection.id.desc())
    tz = str(svc.Resolver(ctx.db).calendar(ctx.user).tz)
    return paginate(ctx.db, stmt, params, lambda c: ser(c, ctx.user.full_name, tz=tz))


@router.delete("/{cid}", status_code=204)
def cancel(cid: int, ctx: Ctx = Depends(get_ctx)):
    c = ctx.db.get(AttendanceCorrection, cid)
    if c is None or c.user_id != ctx.user.id:
        raise NotFound("Correction not found")
    if c.status != "pending":
        raise Conflict("Only a pending request can be cancelled")
    c.status, c.decided_at = "cancelled", utcnow()
    audit(ctx, "attendance.correction_cancelled", "attendance_correction", c.id)
    ctx.db.commit()


def _can_decide(ctx: Ctx) -> bool:
    return ctx.role in ("founder", "hr") or (ctx.role == "manager" and has_permission(ctx.user, "attendance.approve"))


def _decider(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if not _can_decide(ctx):
        raise Forbidden("You cannot review attendance corrections")
    return ctx


@router.get("")
def queue(status: str = "pending", params: PageParams = Depends(), ctx: Ctx = Depends(_decider)):
    """Requests from people in the caller's scope (founder: everyone; HR: their branch; manager: direct reports)."""
    stmt = (select(AttendanceCorrection).join(User, User.id == AttendanceCorrection.user_id).where(user_scope(ctx), User.id != ctx.user.id)
            .order_by(AttendanceCorrection.id.desc()))
    if status != "all":
        stmt = stmt.where(AttendanceCorrection.status == status)
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    res = svc.Resolver(ctx.db)
    name = lambda i: users[i].full_name if i in users else None  # noqa: E731
    return paginate(ctx.db, stmt, params, lambda c: ser(c, name(c.user_id), name(c.decided_by), str(res.calendar(users[c.user_id]).tz) if c.user_id in users else None))


@router.post("/{cid}/decision")
def decide(cid: int, body: DecisionIn, ctx: Ctx = Depends(_decider)):
    c = ctx.db.scalar(select(AttendanceCorrection).join(User, User.id == AttendanceCorrection.user_id)
                      .where(AttendanceCorrection.id == cid, user_scope(ctx)))
    if c is None:
        raise NotFound("Correction not found")  # out-of-scope requests look non-existent
    if c.user_id == ctx.user.id:
        raise Forbidden("You cannot decide your own request")
    if c.status != "pending":
        raise Conflict(f"This request was already {c.status}")
    note = (body.note or "").strip() or None
    if not body.approve and not note:
        raise AppError("Please explain why the request is rejected")
    target = ctx.db.get(User, c.user_id)
    c.status, c.decided_by, c.decided_at, c.decision_note = ("approved" if body.approve else "rejected"), ctx.user.id, utcnow(), note
    if body.approve:
        res = svc.Resolver(ctx.db)
        a = ctx.db.scalar(select(Attendance).where(Attendance.user_id == target.id, Attendance.work_date == c.work_date))
        if a is None:
            a = Attendance(user_id=target.id, work_date=c.work_date, check_in=c.requested_check_in, shift_id=target.shift_id)
            ctx.db.add(a)
        a.check_in, a.check_out, a.source, a.auto_closed = c.requested_check_in, c.requested_check_out, "correction", False
        for b in list(a.breaks):  # breaks that no longer fit inside the corrected session are dropped; the rest are kept
            if as_aware(b.start) < as_aware(c.requested_check_in) or (b.end and as_aware(b.end) > as_aware(c.requested_check_out)):
                a.breaks.remove(b)
        ctx.db.flush()
        svc.finalize(a, target, res)
        c.attendance_id = a.id
    notify(ctx.db, [target.id], f"Attendance correction {c.status}", f"{c.work_date.isoformat()}" + (f": {note}" if note else ""), "attendance", "/attendance")
    audit(ctx, f"attendance.correction_{c.status}", "attendance_correction", c.id, {"user_id": target.id, "work_date": c.work_date.isoformat()})
    ctx.db.commit()
    return ser(c, target.full_name, ctx.user.full_name, str(svc.Resolver(ctx.db).calendar(target).tz))


def as_aware(dt: datetime) -> datetime:
    return eng.utc(dt)
