"""Leave balances as an append-only ledger.

Every change to a balance is a `LeaveLedger` row plus an atomic SQL update of the cached columns on `LeaveBalance` in the same
transaction. Two unique constraints make bookings idempotent: (request_id, kind) so one request is charged and refunded at most once,
and (user, type, year, kind, period) so an accrual period or a year-end carry can run any number of times. Approving a request also
uses a conditional UPDATE ("only if enough is left"), so two concurrent approvals cannot overdraw a balance.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.core.errors import AppError
from app.db.tenant_models import Branch, Holiday, LeaveBalance, LeaveLedger, LeaveRequest, LeaveType, User
from app.modules.attendance.engine import working_weekdays
from app.modules.leave import engine as eng

REMAINING = LeaveBalance.allocated + LeaveBalance.carried_in - LeaveBalance.used - LeaveBalance.expired - LeaveBalance.encashed
# which cached column a ledger kind moves, and in which direction relative to the ledger's signed `days`
_COLUMN = {"grant": ("allocated", 1), "adjust": ("allocated", 1), "carry_in": ("carried_in", 1),
           "use": ("used", -1), "refund": ("used", -1), "expire": ("expired", -1), "encash": ("encashed", -1)}


# ---------------------------------------------------------------- calendar

def person_calendar(db: Session, user: User) -> tuple[frozenset[int], frozenset[date]]:
    """(working weekdays, holidays) for this person: their branch's week, else Monday to Friday."""
    branch = db.get(Branch, user.branch_id) if user.branch_id else None
    return working_weekdays(branch.working_days if branch else None), frozenset(db.scalars(select(Holiday.date)))


def days_for(db: Session, user: User, lt: LeaveType, start: date, end: date, half_day: str | None = None) -> float:
    wd, hol = person_calendar(db, user)
    return eng.count_days(start, end, wd, hol, half_day=half_day, count_all=lt.count_all_days)


# ---------------------------------------------------------------- balances

def get_balance(db: Session, user_id: int, type_id: int, year: int, *, create: bool = True) -> LeaveBalance | None:
    q = select(LeaveBalance).where(LeaveBalance.user_id == user_id, LeaveBalance.leave_type_id == type_id, LeaveBalance.year == year)
    bal = db.scalar(q)
    if bal is None and create:
        try:
            with db.begin_nested():
                db.add(LeaveBalance(user_id=user_id, leave_type_id=type_id, year=year, allocated=0, used=0))
                db.flush()
        except IntegrityError:  # a concurrent request created it first
            pass
        bal = db.scalar(q)
    return bal


def post_entry(db: Session, *, user_id: int, type_id: int, year: int, kind: str, days: float, request_id: int | None = None,
               period: str | None = None, note: str | None = None, actor: int | None = None, guard: bool = False) -> bool:
    """Book one ledger row and move the cached balance. Returns False (and changes nothing) if this exact booking already exists.
    With `guard` the balance move only happens if enough is left (checked inside the UPDATE itself); otherwise AppError is raised."""
    bal = get_balance(db, user_id, type_id, year)
    try:
        with db.begin_nested():
            db.add(LeaveLedger(user_id=user_id, leave_type_id=type_id, year=year, kind=kind, days=days, period=period,
                               request_id=request_id, note=note, created_by=actor))
            db.flush()
    except IntegrityError:
        return False
    col, sign = _COLUMN[kind]
    stmt = update(LeaveBalance).where(LeaveBalance.id == bal.id).values({col: getattr(LeaveBalance, col) + sign * days})
    if guard:
        stmt = stmt.where(REMAINING >= -days - 1e-9)
    if db.execute(stmt).rowcount != 1:
        raise AppError("Not enough balance left", code="insufficient_balance")
    db.refresh(bal)
    return True


def ensure_balances(db: Session, user: User, year: int, as_of: date | None = None) -> None:
    """Make sure the person has a balance row per leave type and that every grant due by `as_of` has been booked."""
    as_of = as_of or utcnow().date()
    booked = {(r.leave_type_id, r.kind, r.period) for r in db.scalars(select(LeaveLedger).where(LeaveLedger.user_id == user.id, LeaveLedger.year == year,
                                                                                               LeaveLedger.kind == "grant"))}
    for lt in db.scalars(select(LeaveType).where(LeaveType.is_active.is_(True))):
        get_balance(db, user.id, lt.id, year)
        if (lt.id, "grant", "opening") in booked:  # balances that predate the ledger already hold this year's grant
            continue
        if lt.accrual == "monthly":
            grants = eng.monthly_grants(lt.annual_quota, year, user.hire_date, as_of)
        else:
            grants = [(str(year), lt.annual_quota)] if lt.annual_quota and (user.hire_date is None or user.hire_date.year <= year) else []
        for period, d in grants:
            if (lt.id, "grant", period) not in booked:
                post_entry(db, user_id=user.id, type_id=lt.id, year=year, kind="grant", days=d, period=period, note="Accrual" if lt.accrual == "monthly" else "Annual grant")
    db.flush()


def pending_days(db: Session, user_id: int, type_id: int, year: int, exclude: set[int] = frozenset()) -> float:
    q = select(LeaveRequest).where(LeaveRequest.user_id == user_id, LeaveRequest.leave_type_id == type_id, LeaveRequest.status == "pending",
                                   LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))
    return sum(r.days for r in db.scalars(q) if r.id not in exclude)


def available(db: Session, user: User, lt: LeaveType, year: int, *, exclude: set[int] = frozenset(), credit: float = 0.0) -> float:
    """Days the person could still ask for: remaining minus what other pending requests already claim (+ `credit`, e.g. the
    days of an approved request that a revision would replace)."""
    ensure_balances(db, user, year)
    bal = get_balance(db, user.id, lt.id, year)
    return round(bal.remaining - pending_days(db, user.id, lt.id, year, exclude) + credit, 4)


def charge(db: Session, req: LeaveRequest, lt: LeaveType, actor: int | None) -> None:
    """Deduct an approved request. Paid types are guarded by a conditional UPDATE so the balance can never go below zero."""
    year = req.start_date.year
    ensure_balances(db, db.get(User, req.user_id), year)
    try:
        post_entry(db, user_id=req.user_id, type_id=lt.id, year=year, kind="use", days=-req.days, request_id=req.id,
                   note=f"{req.start_date} to {req.end_date}", actor=actor, guard=lt.paid)  # False = already charged: never twice
    except AppError:
        raise AppError("Employee no longer has enough balance", code="insufficient_balance") from None


def refund(db: Session, req: LeaveRequest, actor: int | None, note: str = "Leave cancelled") -> bool:
    return post_entry(db, user_id=req.user_id, type_id=req.leave_type_id, year=req.start_date.year, kind="refund", days=req.days,
                      request_id=req.id, note=note, actor=actor)


# ---------------------------------------------------------------- year-end and expiry

def run_maintenance(db: Session, as_of: date | None = None, actor: int | None = None) -> dict:
    """Idempotent: book due accruals, carry last year's unused days forward, and lapse carried days past their expiry month."""
    as_of = as_of or utcnow().date()
    year = as_of.year
    out = {"users": 0, "carried_days": 0.0, "expired_days": 0.0}
    types = list(db.scalars(select(LeaveType).where(LeaveType.is_active.is_(True))))
    for user in db.scalars(select(User).where(User.is_active.is_(True))):
        out["users"] += 1
        if any(t.carry_forward_max > 0 for t in types):
            ensure_balances(db, user, year - 1, as_of)
        ensure_balances(db, user, year, as_of)
        for lt in types:
            if lt.carry_forward_max > 0:
                prev = get_balance(db, user.id, lt.id, year - 1, create=False)
                amount = eng.carry_amount(prev.remaining, lt.carry_forward_max) if prev else 0.0
                if amount > 0 and post_entry(db, user_id=user.id, type_id=lt.id, year=year, kind="carry_in", days=amount, period=f"from-{year - 1}",
                                             note=f"Carried from {year - 1}", actor=actor):
                    out["carried_days"] += amount
            if lt.carry_expiry_months:
                bal = get_balance(db, user.id, lt.id, year, create=False)
                exp = eng.expiry_date(year, lt.carry_expiry_months)
                if bal and bal.carried_in > 0 and as_of > exp:
                    used = [(r.start_date, r.days) for r in db.scalars(select(LeaveRequest).where(
                        LeaveRequest.user_id == user.id, LeaveRequest.leave_type_id == lt.id, LeaveRequest.status == "approved",
                        LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31)))]
                    lapse = eng.carried_to_expire(bal.carried_in, used, exp, bal.remaining)
                    if lapse > 0 and post_entry(db, user_id=user.id, type_id=lt.id, year=year, kind="expire", days=-lapse, period=f"carry-{year}",
                                                note=f"Carried days lapsed on {exp}", actor=actor):
                        out["expired_days"] += lapse
    out["carried_days"], out["expired_days"] = round(out["carried_days"], 2), round(out["expired_days"], 2)
    return out
