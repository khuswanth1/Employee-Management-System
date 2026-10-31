from datetime import date, datetime
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select, update

from app.access import require_permission, same_branch, user_scope
from app.common import PageParams, audit, paginate, to_csv
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import Branch, Holiday, LeaveBalance, LeaveDelegation, LeaveLedger, LeaveRequest, LeaveType, User
from app.deps import Ctx, get_ctx, require_roles
from app.modules.attendance import service as attendance_svc
from app.modules.attendance.engine import working_weekdays
from app.modules.leave import engine as eng
from app.modules.leave import service as svc
from app.modules.notifications.service import notify
from app.modules.webhooks.service import emit

router = APIRouter(prefix="/leave", tags=["leave"])
hr_or_founder = require_roles("hr", "founder")
approver = require_permission("leave.approve", "manager", "hr", "founder")


# ================================================================== schemas

class LeaveTypeIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    annual_quota: float = Field(ge=0, le=366)
    paid: bool = True
    accrual: Literal["annual_upfront", "monthly"] = "annual_upfront"
    carry_forward_max: float = Field(0, ge=0, le=366)
    carry_expiry_months: int | None = Field(None, ge=1, le=12)
    allow_half_day: bool = True
    count_all_days: bool = False
    min_notice_days: int = Field(0, ge=0, le=365)
    max_consecutive_days: float | None = Field(None, gt=0, le=366)
    encashable: bool = False
    encash_max_days: float | None = Field(None, gt=0, le=366)
    is_active: bool = True
    # Changing the quota never touches days already granted. Tick this to add the difference to everyone's current-year balance.
    apply_to_current_year: bool = False

    @model_validator(mode="after")
    def _consistent(self):
        if self.carry_expiry_months and not self.carry_forward_max:
            raise ValueError("A carry-forward expiry needs a carry-forward limit")
        return self


class HolidayIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    date: date


class HolidayUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    date: Date | None = None


class LeaveApply(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    half_day: Literal["first", "second"] | None = None
    reason: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _order(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if self.half_day and self.start_date != self.end_date:
            raise ValueError("A half day is a single day: use the same start and end date")
        return self


class LeaveUpdate(BaseModel):
    leave_type_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    half_day: Literal["first", "second"] | None = None
    reason: str | None = Field(None, max_length=2000)


class Decision(BaseModel):
    approved: bool
    note: str | None = Field(None, max_length=2000)


class DelegationIn(BaseModel):
    delegate_id: int
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _order(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("A delegation can last at most a year")
        return self


class AdjustIn(BaseModel):
    leave_type_id: int
    days: float = Field(ge=-366, le=366)
    note: str = Field(min_length=3, max_length=300)

    @model_validator(mode="after")
    def _nonzero(self):
        if self.days == 0:
            raise ValueError("days cannot be zero")
        return self


class EncashIn(BaseModel):
    leave_type_id: int
    days: float = Field(gt=0, le=366)
    note: str | None = Field(None, max_length=300)


def ser_type(t: LeaveType) -> dict:
    return {"id": t.id, "name": t.name, "annual_quota": t.annual_quota, "paid": t.paid, "accrual": t.accrual, "carry_forward_max": t.carry_forward_max,
            "carry_expiry_months": t.carry_expiry_months, "allow_half_day": t.allow_half_day, "count_all_days": t.count_all_days,
            "min_notice_days": t.min_notice_days, "max_consecutive_days": t.max_consecutive_days, "encashable": t.encashable,
            "encash_max_days": t.encash_max_days, "is_active": t.is_active}


def ser_req(r: LeaveRequest, names: dict, types: dict) -> dict:
    return {
        "id": r.id, "user_id": r.user_id, "user_name": names.get(r.user_id), "leave_type_id": r.leave_type_id,
        "leave_type": types.get(r.leave_type_id), "start_date": r.start_date, "end_date": r.end_date, "days": r.days, "half_day": r.half_day,
        "reason": r.reason, "status": r.status, "decided_by": r.decided_by, "decided_by_name": names.get(r.decided_by), "decided_at": r.decided_at,
        "decision_note": r.decision_note, "created_at": r.created_at, "supersedes_id": r.supersedes_id, "decided_via": r.decided_via,
    }


def _maps(ctx: Ctx):
    return ({u.id: u.full_name for u in ctx.db.scalars(select(User))}, {t.id: t.name for t in ctx.db.scalars(select(LeaveType))})


# ================================================================== types & holidays

@router.get("/types")
def types(include_inactive: bool = False, ctx: Ctx = Depends(get_ctx)):
    q = select(LeaveType).order_by(LeaveType.id)
    if not (include_inactive and ctx.role in ("hr", "founder")):
        q = q.where(LeaveType.is_active.is_(True))
    return {"items": [ser_type(t) for t in ctx.db.scalars(q)]}


@router.post("/types", status_code=201)
def create_type(body: LeaveTypeIn, ctx: Ctx = Depends(hr_or_founder)):
    if ctx.db.scalar(select(LeaveType.id).where(LeaveType.name == body.name)):
        raise Conflict("Leave type already exists")
    t = LeaveType(**body.model_dump(exclude={"apply_to_current_year"}))
    ctx.db.add(t)
    ctx.db.flush()
    for u in ctx.db.scalars(select(User).where(User.is_active.is_(True))):
        svc.ensure_balances(ctx.db, u, utcnow().date().year)
    audit(ctx, "leave_type.created", "leave_type", t.id)
    ctx.db.commit()
    return ser_type(t)


@router.patch("/types/{type_id}")
def update_type(type_id: int, body: LeaveTypeIn, ctx: Ctx = Depends(hr_or_founder)):
    t = ctx.db.get(LeaveType, type_id)
    if t is None:
        raise NotFound()
    if body.name != t.name and ctx.db.scalar(select(LeaveType.id).where(LeaveType.name == body.name, LeaveType.id != t.id)):
        raise Conflict("Leave type already exists")
    delta = body.annual_quota - t.annual_quota
    for k, v in body.model_dump(exclude={"apply_to_current_year"}).items():
        setattr(t, k, v)
    adjusted = 0
    if delta and body.apply_to_current_year and t.accrual == "annual_upfront":
        year = utcnow().date().year
        for u in ctx.db.scalars(select(User).where(User.is_active.is_(True))):
            svc.ensure_balances(ctx.db, u, year)
            adjusted += svc.post_entry(ctx.db, user_id=u.id, type_id=t.id, year=year, kind="adjust", days=delta,
                                       note=f"Quota changed to {t.annual_quota:g}", actor=ctx.user.id)
    # Approved and pending requests are never recalculated when a policy changes.
    audit(ctx, "leave_type.updated", "leave_type", t.id, {"quota_delta": delta, "applied_to_current_year": adjusted})
    ctx.db.commit()
    return ser_type(t)


def _weekend_for_everyone(ctx: Ctx, d: date) -> bool:
    """A holiday on a day nobody works adds nothing. A day that some branch works (e.g. Sunday in a Sunday-Thursday branch) is allowed."""
    weeks = [working_weekdays(b.working_days) for b in ctx.db.scalars(select(Branch)) if b.working_days] + [working_weekdays(None)]
    return all(d.weekday() not in w for w in weeks)


def _check_holiday_date(ctx: Ctx, d: date) -> None:
    if _weekend_for_everyone(ctx, d):
        raise AppError("Holidays must fall on a working day (Monday to Friday, or a day some branch works); weekends are already days off")


@router.get("/holidays")
def holidays(year: int | None = None, ctx: Ctx = Depends(get_ctx)):
    y = year or utcnow().date().year
    rows = ctx.db.scalars(select(Holiday).where(Holiday.date >= date(y, 1, 1), Holiday.date <= date(y, 12, 31)).order_by(Holiday.date))
    return {"items": [{"id": h.id, "name": h.name, "date": h.date} for h in rows]}


@router.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, ctx: Ctx = Depends(hr_or_founder)):
    _check_holiday_date(ctx, body.date)
    if ctx.db.scalar(select(Holiday.id).where(Holiday.date == body.date)):
        raise Conflict("A holiday already exists on this date")
    h = Holiday(name=body.name, date=body.date)
    ctx.db.add(h)
    ctx.db.flush()
    audit(ctx, "holiday.created", "holiday", h.id, {"name": h.name, "date": str(h.date)})
    ctx.db.commit()
    return {"id": h.id, "name": h.name, "date": h.date}


@router.patch("/holidays/{hid}")
def update_holiday(hid: int, body: HolidayUpdate, ctx: Ctx = Depends(hr_or_founder)):
    h = ctx.db.get(Holiday, hid)
    if h is None:
        raise NotFound()
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is None:
        data.pop("name", None)
    if data.get("date") is None:
        data.pop("date", None)
    if "date" in data:
        _check_holiday_date(ctx, data["date"])
        if data["date"] != h.date and ctx.db.scalar(select(Holiday.id).where(Holiday.date == data["date"])):
            raise Conflict("A holiday already exists on this date")
    for k, v in data.items():
        setattr(h, k, v)
    audit(ctx, "holiday.updated", "holiday", h.id, {"fields": sorted(data)})
    ctx.db.commit()
    return {"id": h.id, "name": h.name, "date": h.date}


@router.delete("/holidays/{hid}", status_code=204)
def delete_holiday(hid: int, ctx: Ctx = Depends(hr_or_founder)):
    h = ctx.db.get(Holiday, hid)
    if h is None:
        raise NotFound()
    ctx.db.delete(h)
    audit(ctx, "holiday.deleted", "holiday", hid, {"name": h.name, "date": str(h.date)})
    ctx.db.commit()


# ================================================================== balances

def _balances(ctx: Ctx, user: User, year: int | None = None) -> list[dict]:
    year = year or utcnow().date().year
    svc.ensure_balances(ctx.db, user, year)
    ctx.db.commit()
    tmap = {t.id: t for t in ctx.db.scalars(select(LeaveType))}
    rows = ctx.db.scalars(select(LeaveBalance).where(LeaveBalance.user_id == user.id, LeaveBalance.year == year).order_by(LeaveBalance.leave_type_id))
    out = []
    for b in rows:
        t = tmap.get(b.leave_type_id)
        if t is None or (not t.is_active and not b.allocated and not b.used):
            continue
        pend = svc.pending_days(ctx.db, user.id, t.id, year)
        out.append({"leave_type_id": b.leave_type_id, "leave_type": t.name, "paid": t.paid, "year": b.year, "allocated": b.allocated, "carried_in": b.carried_in,
                    "used": b.used, "expired": b.expired, "encashed": b.encashed, "pending": pend, "remaining": b.remaining, "available": round(b.remaining - pend, 4),
                    "accrual": t.accrual, "encashable": t.encashable})
    return out


def _scoped_user(ctx: Ctx, user_id: int) -> User:
    """Someone the caller may see: founder anyone, HR their branch, a manager their direct reports. Others look non-existent."""
    u = ctx.db.scalar(select(User).where(User.id == user_id, user_scope(ctx)))
    if u is None or (ctx.role == "manager" and u.id == ctx.user.id):
        raise NotFound()
    return u


@router.get("/balances")
def my_balances(year: int | None = None, ctx: Ctx = Depends(get_ctx)):
    return {"items": _balances(ctx, ctx.user, year)}


@router.get("/balances/{user_id}")
def user_balances(user_id: int, year: int | None = None, ctx: Ctx = Depends(require_roles("hr", "founder", "manager"))):
    return {"items": _balances(ctx, _scoped_user(ctx, user_id), year)}


@router.get("/ledger")
def ledger(user_id: int | None = None, leave_type_id: int | None = None, year: int | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    """Every change to a balance, newest first. Yourself, or (HR / founder / manager) someone in your scope."""
    target = ctx.user if user_id in (None, ctx.user.id) else _scoped_user(ctx, user_id) if ctx.role in ("hr", "founder", "manager") else None
    if target is None:
        raise NotFound()
    stmt = select(LeaveLedger).where(LeaveLedger.user_id == target.id).order_by(LeaveLedger.id.desc())
    if leave_type_id:
        stmt = stmt.where(LeaveLedger.leave_type_id == leave_type_id)
    if year:
        stmt = stmt.where(LeaveLedger.year == year)
    names, tnames = _maps(ctx)
    return paginate(ctx.db, stmt, params, lambda e: {"id": e.id, "leave_type_id": e.leave_type_id, "leave_type": tnames.get(e.leave_type_id), "year": e.year,
                                                     "kind": e.kind, "days": e.days, "period": e.period, "request_id": e.request_id, "note": e.note,
                                                     "created_by": names.get(e.created_by), "created_at": e.created_at})


@router.post("/balances/{user_id}/adjust")
def adjust(user_id: int, body: AdjustIn, ctx: Ctx = Depends(hr_or_founder)):
    u = _scoped_user(ctx, user_id)
    lt = ctx.db.get(LeaveType, body.leave_type_id)
    if lt is None:
        raise AppError("Unknown leave type")
    year = utcnow().date().year
    svc.ensure_balances(ctx.db, u, year)
    bal = svc.get_balance(ctx.db, u.id, lt.id, year)
    if bal.remaining + body.days < 0:
        raise AppError(f"This would leave a negative balance ({bal.remaining:g} days remaining)", code="insufficient_balance")
    svc.post_entry(ctx.db, user_id=u.id, type_id=lt.id, year=year, kind="adjust", days=body.days, note=body.note, actor=ctx.user.id)
    audit(ctx, "leave.balance_adjusted", "user", u.id, {"leave_type_id": lt.id, "days": body.days})
    notify(ctx.db, [u.id], "Leave balance adjusted", f"{lt.name}: {body.days:+g} days. {body.note}", "leave", "/leave")
    ctx.db.commit()
    return {"items": _balances(ctx, u)}


@router.post("/balances/{user_id}/encash")
def encash(user_id: int, body: EncashIn, ctx: Ctx = Depends(hr_or_founder)):
    """Record that unused days were paid out. (There is no payroll module yet: this only books the ledger entry.)"""
    u = _scoped_user(ctx, user_id)
    lt = ctx.db.get(LeaveType, body.leave_type_id)
    if lt is None or not lt.encashable:
        raise AppError("This leave type cannot be encashed")
    year = utcnow().date().year
    svc.ensure_balances(ctx.db, u, year)
    bal = svc.get_balance(ctx.db, u.id, lt.id, year)
    if body.days > svc.available(ctx.db, u, lt, year) + 1e-9:
        raise AppError(f"Only {max(0.0, svc.available(ctx.db, u, lt, year)):g} days are available to encash", code="insufficient_balance")
    if lt.encash_max_days is not None and bal.encashed + body.days > lt.encash_max_days + 1e-9:
        raise AppError(f"At most {lt.encash_max_days:g} days per year can be encashed ({bal.encashed:g} already)", code="encash_limit")
    svc.post_entry(ctx.db, user_id=u.id, type_id=lt.id, year=year, kind="encash", days=-body.days, note=body.note or "Encashment", actor=ctx.user.id)
    audit(ctx, "leave.encashed", "user", u.id, {"leave_type_id": lt.id, "days": body.days})
    ctx.db.commit()
    return {"items": _balances(ctx, u)}


@router.post("/maintenance")
def maintenance(ctx: Ctx = Depends(hr_or_founder)):
    """Year-end and accrual run: books due accruals, carries unused days into this year (within each type's limit) and lapses carried
    days past their expiry month. Idempotent: running it again changes nothing. Previous years' approved leave is never touched."""
    result = svc.run_maintenance(ctx.db, utcnow().date(), ctx.user.id)
    audit(ctx, "leave.maintenance", None, None, result)
    ctx.db.commit()
    return result


# ================================================================== requests

def _local_today(ctx: Ctx, user: User) -> date:
    """Today's date where this person works (their branch timezone, else the company's), not the server's: a delegation entered as
    "from today" by someone east of UTC must be active for them straight away."""
    return datetime.now(attendance_svc.Resolver(ctx.db).calendar(user).tz).date()


def _delegators_of(ctx: Ctx, user_id: int) -> list[int]:
    today = _local_today(ctx, ctx.user)
    return list(ctx.db.scalars(select(LeaveDelegation.delegator_id).where(
        LeaveDelegation.delegate_id == user_id, LeaveDelegation.revoked_at.is_(None), LeaveDelegation.start_date <= today, LeaveDelegation.end_date >= today)))


def _approvers(ctx: Ctx, user: User) -> list[int]:
    if user.manager_id:
        today = _local_today(ctx, user)
        delegates = ctx.db.scalars(select(LeaveDelegation.delegate_id).where(
            LeaveDelegation.delegator_id == user.manager_id, LeaveDelegation.revoked_at.is_(None), LeaveDelegation.start_date <= today, LeaveDelegation.end_date >= today))
        return sorted({user.manager_id, *delegates} - {user.id})
    return list(ctx.db.scalars(select(User.id).where(User.role.in_(["hr", "founder"]), User.is_active.is_(True), User.id != user.id)))


def _validate(ctx: Ctx, user: User, *, type_id: int, start: date, end: date, half: str | None, exclude: set[int] = frozenset(),
              supersedes: LeaveRequest | None = None) -> tuple[LeaveType, float]:
    lt = ctx.db.get(LeaveType, type_id)
    if lt is None:
        raise AppError("Unknown leave type")
    if not lt.is_active:
        raise AppError("This leave type is no longer available")
    if start.year != end.year:
        raise AppError("Leave spanning two calendar years must be applied for separately")
    today = utcnow().date()
    if end < today:
        raise AppError("Cannot apply for leave entirely in the past")
    if half and not lt.allow_half_day:
        raise AppError(f"{lt.name} cannot be taken in half days")
    if lt.min_notice_days and (start - today).days < lt.min_notice_days:
        raise AppError(f"{lt.name} needs at least {lt.min_notice_days} days' notice")
    days = svc.days_for(ctx.db, user, lt, start, end, half)
    if days <= 0:
        raise AppError("The selected dates contain no working days")
    if lt.max_consecutive_days and days > lt.max_consecutive_days:
        raise AppError(f"{lt.name} is limited to {lt.max_consecutive_days:g} days at a time")
    skip = set(exclude) | ({supersedes.id} if supersedes else set())
    for o in ctx.db.scalars(select(LeaveRequest).where(LeaveRequest.user_id == user.id, LeaveRequest.status.in_(["pending", "approved"]),
                                                       LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)):
        if o.id not in skip and eng.overlaps(start, end, half, o.start_date, o.end_date, o.half_day):
            raise Conflict("You already have leave overlapping these dates")
    if lt.paid:
        credit = supersedes.days if supersedes and supersedes.leave_type_id == lt.id and supersedes.start_date.year == start.year else 0.0
        left = svc.available(ctx.db, user, lt, start.year, exclude=set(exclude), credit=credit)
        if left < days - 1e-9:
            raise AppError(f"Insufficient {lt.name} balance ({max(0.0, left):g} days available)", code="insufficient_balance")
    return lt, days


def _announce(ctx: Ctx, user: User, r: LeaveRequest, verb: str) -> None:
    span = f"{r.start_date}" if r.start_date == r.end_date else f"{r.start_date} → {r.end_date}"
    notify(ctx.db, _approvers(ctx, user), "Leave request", f"{user.full_name}: {span} ({r.days:g} day{'s' if r.days != 1 else ''}){' [revision]' if r.supersedes_id else ''}",
           "leave", "/leave/approvals")
    emit(ctx.db, "leave.requested", {"id": r.id, "user_id": user.id, "days": r.days})
    audit(ctx, f"leave.{verb}", "leave_request", r.id)


@router.post("/requests", status_code=201)
def apply(body: LeaveApply, ctx: Ctx = Depends(get_ctx)):
    lt, days = _validate(ctx, ctx.user, type_id=body.leave_type_id, start=body.start_date, end=body.end_date, half=body.half_day)
    r = LeaveRequest(user_id=ctx.user.id, leave_type_id=lt.id, start_date=body.start_date, end_date=body.end_date, days=days, half_day=body.half_day, reason=body.reason)
    ctx.db.add(r)
    ctx.db.flush()
    _announce(ctx, ctx.user, r, "requested")
    ctx.db.commit()
    return ser_req(r, *_maps(ctx))


def _own(ctx: Ctx, rid: int) -> LeaveRequest:
    r = ctx.db.get(LeaveRequest, rid)
    if r is None or r.user_id != ctx.user.id:
        raise NotFound()
    return r


@router.patch("/requests/{rid}")
def modify(rid: int, body: LeaveUpdate, ctx: Ctx = Depends(get_ctx)):
    """Change your own request while it is still pending (dates, type, half day, reason). Approved leave is changed with /revise."""
    r = _own(ctx, rid)
    if r.status != "pending":
        raise Conflict("Only a pending request can be edited. To change approved leave, request a revision.")
    data = body.model_dump(exclude_unset=True)
    start, end = data.get("start_date", r.start_date), data.get("end_date", r.end_date)
    half = data["half_day"] if "half_day" in data else (r.half_day if start == end else None)
    if end < start:
        raise AppError("end_date cannot be before start_date", status_code=422)
    if half and start != end:
        raise AppError("A half day is a single day: use the same start and end date", status_code=422)
    orig = ctx.db.get(LeaveRequest, r.supersedes_id) if r.supersedes_id else None
    orig = orig if orig and orig.status == "approved" else None
    lt, days = _validate(ctx, ctx.user, type_id=data.get("leave_type_id", r.leave_type_id), start=start, end=end, half=half, exclude={r.id}, supersedes=orig)
    r.leave_type_id, r.start_date, r.end_date, r.days, r.half_day = lt.id, start, end, days, half
    if "reason" in data:
        r.reason = data["reason"]
    audit(ctx, "leave.modified", "leave_request", r.id, {"fields": sorted(data)})
    notify(ctx.db, _approvers(ctx, ctx.user), "Leave request updated", f"{ctx.user.full_name} changed a pending request: {start} → {end} ({days:g} days)", "leave", "/leave/approvals")
    ctx.db.commit()
    return ser_req(r, *_maps(ctx))


@router.post("/requests/{rid}/revise", status_code=201)
def revise(rid: int, body: LeaveApply, ctx: Ctx = Depends(get_ctx)):
    """Ask to change approved, not-yet-started leave. A new pending request is created; the approved one stays in force (and keeps
    its days charged) until the revision is approved, at which point it is replaced atomically."""
    orig = _own(ctx, rid)
    if orig.status != "approved" or orig.start_date <= utcnow().date():
        raise Conflict("Only approved leave that has not started yet can be revised")
    if ctx.db.scalar(select(LeaveRequest.id).where(LeaveRequest.supersedes_id == orig.id, LeaveRequest.status == "pending")):
        raise Conflict("There is already a pending revision for this leave")
    lt, days = _validate(ctx, ctx.user, type_id=body.leave_type_id, start=body.start_date, end=body.end_date, half=body.half_day, supersedes=orig)
    r = LeaveRequest(user_id=ctx.user.id, leave_type_id=lt.id, start_date=body.start_date, end_date=body.end_date, days=days, half_day=body.half_day,
                     reason=body.reason, supersedes_id=orig.id)
    ctx.db.add(r)
    ctx.db.flush()
    _announce(ctx, ctx.user, r, "revision_requested")
    ctx.db.commit()
    return ser_req(r, *_maps(ctx))


@router.get("/requests/mine")
def my_requests(status: str | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(LeaveRequest).where(LeaveRequest.user_id == ctx.user.id).order_by(LeaveRequest.id.desc())
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    names, types_ = _maps(ctx)
    return paginate(ctx.db, stmt, params, lambda r: ser_req(r, names, types_))


@router.get("/requests")
def approvals(status: str | None = None, user_id: int | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(approver)):
    stmt = select(LeaveRequest).order_by(LeaveRequest.id.desc())
    if ctx.role != "founder":
        delegators = _delegators_of(ctx, ctx.user.id)
        scope = or_(user_scope(ctx), and_(User.manager_id.in_(delegators), User.id != ctx.user.id)) if delegators else user_scope(ctx)
        stmt = stmt.join(User, User.id == LeaveRequest.user_id).where(scope)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if user_id:
        stmt = stmt.where(LeaveRequest.user_id == user_id)
    names, types_ = _maps(ctx)
    return paginate(ctx.db, stmt, params, lambda r: ser_req(r, names, types_))


def _authority(ctx: Ctx, applicant: User) -> int | None:
    """May the caller decide this person's leave? Returns the delegator whose authority is used (None = the caller's own)."""
    if applicant.id == ctx.user.id:
        raise Forbidden("You cannot decide your own leave request")
    if ctx.role == "founder":
        return None
    if ctx.role == "hr":
        if not same_branch(ctx.user, applicant):
            raise Forbidden("This request belongs to another branch")
        return None
    if applicant.manager_id == ctx.user.id and same_branch(ctx.user, applicant):
        return None
    for delegator_id in _delegators_of(ctx, ctx.user.id):
        delegator = ctx.db.get(User, delegator_id)
        if delegator and delegator.is_active and applicant.manager_id == delegator.id and same_branch(delegator, applicant):
            return delegator.id
    raise Forbidden("You can only decide requests from your direct reports")


@router.post("/requests/{rid}/decision")
def decide(rid: int, body: Decision, ctx: Ctx = Depends(approver)):
    r = ctx.db.get(LeaveRequest, rid)
    if r is None:
        raise NotFound()
    applicant = ctx.db.get(User, r.user_id)
    via = _authority(ctx, applicant)
    if r.status != "pending":
        raise Conflict(f"Request is already {r.status}")
    new_status = "approved" if body.approved else "rejected"
    # Claim the request first with a compare-and-set, so two simultaneous decisions cannot both proceed (and charge twice).
    won = ctx.db.execute(update(LeaveRequest).where(LeaveRequest.id == rid, LeaveRequest.status == "pending").values(
        status=new_status, decided_by=ctx.user.id, decided_at=utcnow(), decision_note=body.note, decided_via=via))
    if won.rowcount != 1:
        raise Conflict("Request was just decided by someone else")
    ctx.db.refresh(r)
    if body.approved:
        lt = ctx.db.get(LeaveType, r.leave_type_id)
        if r.supersedes_id:  # a revision replaces the leave it revises, in this same transaction
            old = ctx.db.get(LeaveRequest, r.supersedes_id)
            if old is not None and ctx.db.execute(update(LeaveRequest).where(LeaveRequest.id == old.id, LeaveRequest.status == "approved").values(status="superseded")).rowcount == 1:
                svc.refund(ctx.db, old, ctx.user.id, note=f"Replaced by revision #{r.id}")
                ctx.db.refresh(old)
        svc.charge(ctx.db, r, lt, ctx.user.id)
    notify(ctx.db, [r.user_id], f"Leave {r.status}", body.note or f"{r.start_date} → {r.end_date}", "leave", "/leave")
    emit(ctx.db, "leave.decided", {"id": r.id, "user_id": r.user_id, "status": r.status})
    audit(ctx, f"leave.{r.status}", "leave_request", r.id, {"via_delegation_of": via} if via else None)
    ctx.db.commit()
    return ser_req(r, *_maps(ctx))


@router.post("/requests/{rid}/cancel")
def cancel(rid: int, ctx: Ctx = Depends(get_ctx)):
    r = _own(ctx, rid)
    if r.status == "pending":
        pass
    elif r.status == "approved" and r.start_date > utcnow().date():
        pass
    else:
        raise Conflict("This request can no longer be cancelled")
    was = r.status
    if ctx.db.execute(update(LeaveRequest).where(LeaveRequest.id == rid, LeaveRequest.status == was).values(status="cancelled")).rowcount != 1:
        raise Conflict("This request can no longer be cancelled")
    ctx.db.refresh(r)
    if was == "approved":
        svc.refund(ctx.db, r, ctx.user.id)  # idempotent: the (request, 'refund') row exists at most once
        notify(ctx.db, _approvers(ctx, ctx.user), "Approved leave cancelled", f"{ctx.user.full_name} cancelled {r.start_date} → {r.end_date}", "leave", "/leave/approvals")
    audit(ctx, "leave.cancelled", "leave_request", r.id)
    ctx.db.commit()
    return ser_req(r, *_maps(ctx))


# ================================================================== delegation

def _ser_delegation(d: LeaveDelegation, names: dict, today: date) -> dict:
    return {"id": d.id, "delegator_id": d.delegator_id, "delegator": names.get(d.delegator_id), "delegate_id": d.delegate_id, "delegate": names.get(d.delegate_id),
            "start_date": d.start_date, "end_date": d.end_date, "revoked": d.revoked_at is not None,
            "active": d.revoked_at is None and d.start_date <= today <= d.end_date}


@router.get("/delegations")
def delegations(ctx: Ctx = Depends(get_ctx)):
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    today = _local_today(ctx, ctx.user)
    rows = ctx.db.scalars(select(LeaveDelegation).where(or_(LeaveDelegation.delegator_id == ctx.user.id, LeaveDelegation.delegate_id == ctx.user.id))
                          .order_by(LeaveDelegation.id.desc()).limit(50))
    return {"items": [{**_ser_delegation(d, names, today), "direction": "given" if d.delegator_id == ctx.user.id else "received"} for d in rows]}


@router.post("/delegations", status_code=201)
def delegate(body: DelegationIn, ctx: Ctx = Depends(require_permission("leave.approve", "manager"))):
    """A manager lets another approver decide their direct reports' leave for a period."""
    if body.end_date < _local_today(ctx, ctx.user):
        raise AppError("The delegation period is already over")
    d = ctx.db.get(User, body.delegate_id)
    if d is None or not d.is_active or d.id == ctx.user.id:
        raise AppError("Choose another active colleague")
    if d.role not in ("manager", "hr", "founder"):
        raise AppError("Only a manager, HR or a founder can be given approval rights")
    row = LeaveDelegation(delegator_id=ctx.user.id, delegate_id=d.id, start_date=body.start_date, end_date=body.end_date)
    ctx.db.add(row)
    ctx.db.flush()
    notify(ctx.db, [d.id], "Leave approvals delegated to you", f"{ctx.user.full_name} asked you to decide their team's leave {body.start_date} → {body.end_date}", "leave", "/leave/approvals")
    audit(ctx, "leave.delegated", "user", d.id, {"start": str(body.start_date), "end": str(body.end_date)})
    ctx.db.commit()
    return _ser_delegation(row, {u.id: u.full_name for u in ctx.db.scalars(select(User))}, _local_today(ctx, ctx.user))


@router.delete("/delegations/{did}", status_code=204)
def revoke_delegation(did: int, ctx: Ctx = Depends(get_ctx)):
    d = ctx.db.get(LeaveDelegation, did)
    if d is None or (d.delegator_id != ctx.user.id and ctx.role != "founder"):
        raise NotFound()
    if d.revoked_at is None:
        d.revoked_at = utcnow()
        audit(ctx, "leave.delegation_revoked", "user", d.delegate_id)
        ctx.db.commit()


# ================================================================== calendar & reports

@router.get("/calendar")
def calendar(start: date, end: date, ctx: Ctx = Depends(get_ctx)):
    if (end - start).days > 400:
        raise AppError("Range too large")
    stmt = select(LeaveRequest).where(LeaveRequest.status == "approved", LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)
    if ctx.role == "manager":
        stmt = stmt.join(User, User.id == LeaveRequest.user_id).where(or_(User.manager_id == ctx.user.id, User.id == ctx.user.id))
    elif ctx.role == "hr" and ctx.user.branch_id is not None:
        stmt = stmt.join(User, User.id == LeaveRequest.user_id).where(user_scope(ctx))
    elif ctx.role in ("employee", "board_member"):
        stmt = stmt.where(LeaveRequest.user_id == ctx.user.id)
    names, types_ = _maps(ctx)
    hol = ctx.db.scalars(select(Holiday).where(Holiday.date >= start, Holiday.date <= end))
    return {"leaves": [ser_req(r, names, types_) for r in ctx.db.scalars(stmt)],
            "holidays": [{"id": h.id, "name": h.name, "date": h.date} for h in hol]}


reports = require_permission("reports.view", "manager", "hr", "founder")


def _balance_rows(ctx: Ctx, year: int, branch_id: int | None, department_id: int | None) -> list[dict]:
    stmt = select(User).where(User.is_active.is_(True), user_scope(ctx)).order_by(User.full_name)
    if branch_id:
        stmt = stmt.where(User.branch_id == branch_id)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    tmap = {t.id: t for t in ctx.db.scalars(select(LeaveType))}
    out = []
    for u in ctx.db.scalars(stmt):
        svc.ensure_balances(ctx.db, u, year)
        for b in ctx.db.scalars(select(LeaveBalance).where(LeaveBalance.user_id == u.id, LeaveBalance.year == year).order_by(LeaveBalance.leave_type_id)):
            t = tmap.get(b.leave_type_id)
            if t is None:
                continue
            out.append({"user_id": u.id, "employee": u.full_name, "leave_type": t.name, "year": year, "allocated": b.allocated, "carried_in": b.carried_in,
                        "used": b.used, "expired": b.expired, "encashed": b.encashed, "pending": svc.pending_days(ctx.db, u.id, t.id, year), "remaining": b.remaining})
    ctx.db.commit()
    return out


@router.get("/reports/balances")
def report_balances(year: int | None = None, branch_id: int | None = None, department_id: int | None = None, ctx: Ctx = Depends(reports)):
    return {"items": _balance_rows(ctx, year or utcnow().date().year, branch_id, department_id)}


@router.get("/reports/balances.csv")
def report_balances_csv(year: int | None = None, branch_id: int | None = None, department_id: int | None = None, ctx: Ctx = Depends(reports)):
    rows = _balance_rows(ctx, year or utcnow().date().year, branch_id, department_id)
    head = ["Employee", "Leave type", "Year", "Allocated", "Carried in", "Used", "Expired", "Encashed", "Pending", "Remaining"]
    body = to_csv(head, [[r["employee"], r["leave_type"], r["year"], r["allocated"], r["carried_in"], r["used"], r["expired"], r["encashed"], r["pending"], r["remaining"]] for r in rows])
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="leave-balances.csv"'})


@router.get("/reports/usage")
def report_usage(year: int | None = None, ctx: Ctx = Depends(reports)):
    """Approved leave days by type and by month (of the start date), plus how many requests are in each status."""
    year = year or utcnow().date().year
    base = select(LeaveRequest).where(LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))
    if ctx.role != "founder":
        base = base.join(User, User.id == LeaveRequest.user_id).where(user_scope(ctx))
    tnames = {t.id: t.name for t in ctx.db.scalars(select(LeaveType))}
    by_type: dict[str, list[float]] = {}
    status_counts: dict[str, int] = {}
    for r in ctx.db.scalars(base):
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
        if r.status == "approved":
            by_type.setdefault(tnames.get(r.leave_type_id, "?"), [0.0] * 12)[r.start_date.month - 1] += r.days
    return {"year": year, "by_type": [{"leave_type": k, "months": v, "total": round(sum(v), 2)} for k, v in sorted(by_type.items())], "statuses": status_counts}
