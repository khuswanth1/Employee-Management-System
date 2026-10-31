"""Builds payslips from the pay structure, leave, attendance and the company calendar (the arithmetic lives in engine.py)."""
from __future__ import annotations

import calendar as pycal
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import get_setting
from app.db.tenant_models import (Attendance, Compensation, LeaveRequest, LeaveType, Payslip, PayslipLine, PayrollRun, SalaryComponent, User)
from app.modules.leave.service import person_calendar
from app.modules.payroll import engine as eng

PAID_ROLES = ("employee", "manager", "hr", "founder")
BASES = ("ignore", "attendance")
# attendance status -> credit for that scheduled day
CREDIT = {"present": Decimal(1), "half_day": Decimal("0.5"), "short_day": Decimal(0), "in_progress": Decimal(1)}


def period_of(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, pycal.monthrange(year, month)[1])


def policy(db: Session) -> dict:
    """The company's payroll settings, frozen onto each run when it is calculated."""
    basis = get_setting(db, "payroll_attendance_basis", "ignore")
    try:
        mult = Decimal(get_setting(db, "payroll_overtime_multiplier", "0"))
    except Exception:  # noqa: BLE001 - a bad value must not stop payroll, it just means overtime is not paid
        mult = Decimal(0)
    try:
        std = Decimal(get_setting(db, "standard_work_hours", "8"))
    except Exception:  # noqa: BLE001
        std = Decimal(8)
    return {"attendance_basis": basis if basis in BASES else "ignore", "overtime_multiplier": str(mult), "standard_hours": str(std),
            "currency": (get_setting(db, "payroll_currency", "USD").strip().upper() or "USD")[:3]}


def current_compensation(db: Session, user_id: int, on: date) -> Compensation | None:
    return db.scalar(select(Compensation).where(Compensation.user_id == user_id, Compensation.effective_from <= on)
                     .order_by(Compensation.effective_from.desc()).limit(1))


def _leave_facts(db: Session, user: User, start: date, end: date, weekdays, holidays) -> tuple[dict, dict]:
    unpaid: dict[date, Decimal] = {}
    paid: dict[date, Decimal] = {}
    types = {t.id: t for t in db.scalars(select(LeaveType))}
    q = select(LeaveRequest).where(LeaveRequest.user_id == user.id, LeaveRequest.status == "approved",
                                   LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)
    for r in db.scalars(q):
        t = types.get(r.leave_type_id)
        bucket = paid if (t is not None and t.paid) else unpaid
        d = max(r.start_date, start)
        while d <= min(r.end_date, end):
            if d.weekday() in weekdays and d not in holidays:
                bucket[d] = min(Decimal(1), bucket.get(d, Decimal(0)) + (Decimal("0.5") if r.half_day else Decimal(1)))
            d += timedelta(days=1)
    return unpaid, paid


def _attendance_facts(db: Session, user_id: int, start: date, end: date, weekdays, holidays) -> tuple[dict, int]:
    credits: dict[date, Decimal] = {}
    overtime = 0
    for a in db.scalars(select(Attendance).where(Attendance.user_id == user_id, Attendance.work_date >= start, Attendance.work_date <= end)):
        overtime += a.overtime_minutes or 0
        if a.work_date in holidays or a.work_date.weekday() not in weekdays:
            continue  # work on a day off earns overtime (if enabled), not a "present" credit
        credits[a.work_date] = CREDIT.get(a.status or "", Decimal(1) if a.check_in else Decimal(0))
    return credits, overtime


def build_slip(db: Session, run: PayrollRun, user: User, comp: Compensation, pol: dict, components: dict[int, SalaryComponent]) -> eng.Payslip:
    weekdays, holidays = person_calendar(db, user)
    left = user.offboarded_at.date() if user.status == "offboarded" and user.offboarded_at else None
    unpaid, paid = _leave_facts(db, user, run.period_start, run.period_end, weekdays, holidays)
    attendance, overtime = (None, 0)
    mult = Decimal(pol["overtime_multiplier"])
    if pol["attendance_basis"] == "attendance" or mult > 0:
        credits, overtime = _attendance_facts(db, user.id, run.period_start, run.period_end, weekdays, holidays)
        attendance = credits if pol["attendance_basis"] == "attendance" else None
    lines = []
    for ln in comp.lines:
        c = components.get(ln.component_id)
        if c is not None and c.is_active:
            lines.append(eng.Line(eng.Component(c.code, c.name, c.kind, c.calc, c.prorate, c.cap_minor), ln.value))
    return eng.compute(start=run.period_start, end=run.period_end, weekdays=weekdays, holidays=holidays, basic_minor=comp.basic_minor, lines=lines,
                       hired_on=user.hire_date, left_on=left, unpaid_leave=unpaid, paid_leave=paid, attendance=attendance, overtime_minutes=overtime,
                       overtime_multiplier=mult, standard_hours=Decimal(pol["standard_hours"]))


def _fill(slip: Payslip, user: User, comp: Compensation, calc: eng.Payslip, currency: str, adjustments: list[tuple[str, str, int]]) -> Payslip:
    if adjustments:
        eng.apply_adjustments(calc, [(n, k, eng.from_minor(a)) for n, k, a in adjustments])
    slip.compensation_id, slip.currency = comp.id, currency
    slip.employee_name, slip.employee_code, slip.designation = user.full_name, user.employee_code, user.designation
    slip.basic_minor, slip.gross_minor = eng.to_minor(calc.basic), eng.to_minor(calc.gross)
    slip.deductions_minor, slip.net_minor, slip.warnings = eng.to_minor(calc.deductions), eng.to_minor(calc.net), calc.warnings
    slip.facts = {"scheduled_days": calc.scheduled_days, "employed_days": calc.employed_days, "payable_days": str(calc.payable_days),
                  "unpaid_leave_days": str(calc.unpaid_leave_days), "paid_leave_days": str(calc.paid_leave_days),
                  "absent_days": str(calc.absent_days), "overtime_hours": str(calc.overtime_hours)}
    slip.lines.clear()
    for pl in calc.lines:
        slip.lines.append(PayslipLine(code=pl.code, name=pl.name, kind=pl.kind, amount_minor=eng.to_minor(pl.amount), basis=pl.basis, is_adjustment=pl.code == "ADJ"))
    return slip


def _store(db: Session, run: PayrollRun, user: User, comp: Compensation, calc: eng.Payslip, currency: str, adjustments: list[tuple[str, str, int]]) -> Payslip:
    slip = Payslip(run_id=run.id, user_id=user.id)
    _fill(slip, user, comp, calc, currency, adjustments)
    db.add(slip)
    return slip


def calculate_run(db: Session, run: PayrollRun) -> dict:
    """(Re)build every payslip of a draft run from today's pay structures. One-off adjustments already entered are kept."""
    pol = policy(db)
    kept: dict[int, list[tuple[str, str, int]]] = {}
    for s in db.scalars(select(Payslip).where(Payslip.run_id == run.id)):
        kept[s.user_id] = [(ln.name, ln.kind, ln.amount_minor) for ln in s.lines if ln.is_adjustment]
        db.delete(s)
    db.flush()
    components = {c.id: c for c in db.scalars(select(SalaryComponent))}
    skipped, count = [], 0
    people = db.scalars(select(User).where(User.role.in_(PAID_ROLES)).order_by(User.full_name))
    for u in people:
        if u.status == "pending_approval" or (u.hire_date and u.hire_date > run.period_end):
            continue
        if not u.is_active and u.status != "suspended" and not (u.status == "offboarded" and u.offboarded_at and u.offboarded_at.date() >= run.period_start):
            continue
        comp = current_compensation(db, u.id, run.period_end)
        if comp is None:
            skipped.append({"user_id": u.id, "name": u.full_name, "reason": "no pay structure set up"})
            continue
        calc = build_slip(db, run, u, comp, pol, components)
        _store(db, run, u, comp, calc, comp.currency, kept.get(u.id, []))
        count += 1
    run.settings, run.skipped = pol, skipped
    db.flush()
    return {"payslips": count, "skipped": len(skipped)}


def rebuild_slip(db: Session, slip: Payslip, adjustments: list[tuple[str, str, int]]) -> None:
    """Recompute one payslip of a draft run, in place, with the given set of one-off adjustments."""
    run, user, comp = db.get(PayrollRun, slip.run_id), db.get(User, slip.user_id), db.get(Compensation, slip.compensation_id)
    components = {c.id: c for c in db.scalars(select(SalaryComponent))}
    calc = build_slip(db, run, user, comp, run.settings or policy(db), components)
    _fill(slip, user, comp, calc, comp.currency, adjustments)
    db.flush()
