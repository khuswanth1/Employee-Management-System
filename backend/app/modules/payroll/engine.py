"""Payroll arithmetic. Pure functions: no database, no clock, exact decimals.

This module contains NO statutory rules (income tax, social security, provident fund, ...). Every earning and deduction is a
`Component` the company configures (fixed amount, % of basic, or % of gross, optionally capped). Which rules apply in a
jurisdiction, and at what rates, must be taken from the authority's current published rules and verified before production use.

Money is handled as Decimal and stored as integer minor units (two decimals assumed); percentages as basis points (1.25% = 125).

Pay for the period
* scheduled days   = working days of the person's calendar inside the period (their branch's week, minus holidays)
* employed days    = scheduled days between the hire date and the last working day
* each employed day earns a credit 0..1: 1, minus unpaid leave; with the "attendance" basis it is instead what was actually worked
  (present 1, half day 0.5, short day 0) plus paid leave, never above 1 minus unpaid leave
* payable days     = sum of credits; basic pay = monthly basic x payable days / scheduled days
* overtime         = overtime hours x (basic / (scheduled days x standard hours)) x multiplier (0 = overtime is not paid)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def to_minor(x: Decimal) -> int:
    return int((money(x) * 100).to_integral_value())


def from_minor(n: int) -> Decimal:
    return (Decimal(n) / 100).quantize(CENT)


def pct(bp: int) -> Decimal:
    return Decimal(bp) / Decimal(10000)


@dataclass(frozen=True)
class Component:
    code: str
    name: str
    kind: str          # earning | deduction
    calc: str          # fixed | percent_of_basic | percent_of_gross (gross only for deductions)
    prorate: bool = True   # fixed earnings shrink with unpaid days
    cap_minor: int | None = None


@dataclass(frozen=True)
class Line:
    component: Component
    value: int         # minor units for fixed, basis points for percentages


@dataclass
class PayLine:
    code: str
    name: str
    kind: str
    amount: Decimal
    basis: str


@dataclass
class Payslip:
    scheduled_days: int
    employed_days: int
    payable_days: Decimal
    unpaid_leave_days: Decimal
    absent_days: Decimal
    paid_leave_days: Decimal
    overtime_hours: Decimal
    basic: Decimal
    gross: Decimal
    deductions: Decimal
    net: Decimal
    lines: list[PayLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def working_dates(start: date, end: date, weekdays: frozenset[int], holidays: frozenset[date] | set[date]) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() in weekdays and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def _capped(amount: Decimal, cap_minor: int | None) -> Decimal:
    return min(amount, from_minor(cap_minor)) if cap_minor is not None else amount


def compute(*, start: date, end: date, weekdays: frozenset[int], holidays: frozenset[date] | set[date], basic_minor: int, lines: list[Line],
            hired_on: date | None = None, left_on: date | None = None, unpaid_leave: dict[date, Decimal] | None = None,
            paid_leave: dict[date, Decimal] | None = None, attendance: dict[date, Decimal] | None = None, overtime_minutes: int = 0,
            overtime_multiplier: Decimal = ZERO, standard_hours: Decimal = Decimal("8")) -> Payslip:
    """`attendance` None = pay for every employed day except unpaid leave; a dict (date -> credit) = pay what was worked."""
    unpaid_leave, paid_leave = unpaid_leave or {}, paid_leave or {}
    days = working_dates(start, end, weekdays, holidays)
    scheduled = len(days)
    warnings: list[str] = []
    payable = unpaid_total = absent = paid_total = ZERO
    employed = 0
    for d in days:
        if (hired_on and d < hired_on) or (left_on and d > left_on):
            continue
        employed += 1
        unpaid = min(ONE, unpaid_leave.get(d, ZERO))
        paid = min(ONE - unpaid, paid_leave.get(d, ZERO))
        if attendance is None:
            credit = ONE - unpaid
        else:
            worked = attendance.get(d, ZERO)
            credit = min(ONE - unpaid, worked + paid)
            if worked + paid + unpaid < ONE:
                absent += ONE - worked - paid - unpaid
        payable += credit
        unpaid_total += unpaid
        paid_total += paid
    if scheduled == 0:
        warnings.append("no_working_days")
        factor = ZERO
    else:
        factor = payable / Decimal(scheduled)
    basic_full = from_minor(basic_minor)
    basic = money(basic_full * factor)
    out: list[PayLine] = []
    if factor != ONE:
        basis = f"{payable:g} of {scheduled} working days"
    else:
        basis = "full month"
    out.append(PayLine("BASIC", "Basic salary", "earning", basic, basis))

    earnings = ZERO
    for ln in (x for x in lines if x.component.kind == "earning"):
        c = ln.component
        if c.calc == "fixed":
            amt = money(from_minor(ln.value) * (factor if c.prorate else ONE))
            desc = "fixed" + (" (prorated)" if c.prorate and factor != ONE else "")
        elif c.calc == "percent_of_basic":
            amt = money(basic * pct(ln.value))
            desc = f"{pct(ln.value) * 100:g}% of basic"
        else:
            warnings.append(f"invalid_calc:{c.code}")
            continue
        amt = money(_capped(amt, c.cap_minor))
        earnings += amt
        out.append(PayLine(c.code, c.name, "earning", amt, desc + (" (capped)" if c.cap_minor is not None and amt == from_minor(c.cap_minor) else "")))

    overtime_hours = (Decimal(overtime_minutes) / 60).quantize(Decimal("0.01"))
    overtime = ZERO
    if overtime_multiplier > 0 and overtime_minutes > 0 and scheduled and standard_hours > 0:
        hourly = basic_full / (Decimal(scheduled) * standard_hours)
        overtime = money(hourly * overtime_hours * overtime_multiplier)
        out.append(PayLine("OVERTIME", "Overtime", "earning", overtime, f"{overtime_hours:g} h x {overtime_multiplier:g}"))
    gross = money(basic + earnings + overtime)

    deductions = ZERO
    for ln in (x for x in lines if x.component.kind == "deduction"):
        c = ln.component
        if c.calc == "fixed":
            amt, desc = money(from_minor(ln.value)), "fixed"
        elif c.calc == "percent_of_basic":
            amt, desc = money(basic * pct(ln.value)), f"{pct(ln.value) * 100:g}% of basic"
        elif c.calc == "percent_of_gross":
            amt, desc = money(gross * pct(ln.value)), f"{pct(ln.value) * 100:g}% of gross"
        else:
            warnings.append(f"invalid_calc:{c.code}")
            continue
        amt = money(_capped(amt, c.cap_minor))
        deductions += amt
        out.append(PayLine(c.code, c.name, "deduction", amt, desc + (" (capped)" if c.cap_minor is not None and amt == from_minor(c.cap_minor) else "")))
    net = money(gross - deductions)
    if net < 0:
        warnings.append("deductions_exceed_pay")
    return Payslip(scheduled, employed, payable, unpaid_total, absent, paid_total, overtime_hours, basic, gross, money(deductions), net, out, warnings)


def apply_adjustments(slip: Payslip, adjustments: list[tuple[str, str, Decimal]]) -> Payslip:
    """One-off lines (bonus, advance recovery, correction): (name, kind, amount). Totals are recomputed; a net below zero is flagged."""
    earn = sum((a for _, k, a in adjustments if k == "earning"), ZERO)
    ded = sum((a for _, k, a in adjustments if k == "deduction"), ZERO)
    for name, kind, amt in adjustments:
        slip.lines.append(PayLine("ADJ", name, kind, money(amt), "one-off adjustment"))
    slip.gross = money(slip.gross + earn)
    slip.deductions = money(slip.deductions + ded)
    slip.net = money(slip.gross - slip.deductions)
    slip.warnings = [w for w in slip.warnings if w != "deductions_exceed_pay"] + (["deductions_exceed_pay"] if slip.net < 0 else [])
    return slip
