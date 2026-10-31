"""Payroll arithmetic: pure-function tests with exact decimals."""
from datetime import date
from decimal import Decimal as D

from app.modules.payroll import engine as e

MON_FRI = frozenset({0, 1, 2, 3, 4})
JAN = (date(2026, 1, 1), date(2026, 1, 31))      # 22 working days Mon-Fri: 1 January 2026 is a Thursday


def comp(code, kind, calc, **kw):
    return e.Component(code, code.title(), kind, calc, **kw)


def run(basic="3000.00", lines=(), **kw):
    kw.setdefault("weekdays", MON_FRI)
    kw.setdefault("holidays", frozenset())
    return e.compute(start=JAN[0], end=JAN[1], basic_minor=int(D(basic) * 100), lines=list(lines), **kw)


def amounts(slip, kind):
    return {l.code: l.amount for l in slip.lines if l.kind == kind}


def test_money_helpers_round_half_up_and_round_trip():
    assert e.money(D("2.345")) == D("2.35") and e.money(D("2.344")) == D("2.34")
    assert e.to_minor(D("19.99")) == 1999 and e.from_minor(1999) == D("19.99")
    assert e.pct(1250) == D("0.125")


def test_a_full_month_pays_the_full_basic():
    s = run()
    assert (s.scheduled_days, s.employed_days, s.payable_days) == (22, 22, 22)
    assert s.basic == s.gross == s.net == D("3000.00") and s.deductions == 0 and s.warnings == []


def test_unpaid_leave_reduces_basic_in_proportion():
    s = run(unpaid_leave={date(2026, 1, 5): D(1), date(2026, 1, 6): D("0.5")})
    assert s.unpaid_leave_days == D("1.5") and s.payable_days == D("20.5")
    assert s.basic == e.money(D(3000) * D("20.5") / 22) == D("2795.45")


def test_holidays_and_the_branch_week_define_the_scheduled_days():
    assert run(holidays=frozenset({date(2026, 1, 5)})).scheduled_days == 21
    sun_thu = frozenset({6, 0, 1, 2, 3})
    assert e.working_dates(date(2026, 1, 9), date(2026, 1, 11), sun_thu, set()) == [date(2026, 1, 11)]   # Fri, Sat off; Sunday works
    assert e.working_dates(date(2026, 1, 9), date(2026, 1, 11), MON_FRI, set()) == [date(2026, 1, 9)]


def test_joining_and_leaving_mid_month_prorate_by_working_days():
    s = run(hired_on=date(2026, 1, 12))                                      # first day Monday 12th: 15 working days left
    assert (s.employed_days, s.payable_days) == (15, 15) and s.basic == e.money(D(3000) * 15 / 22)
    s = run(left_on=date(2026, 1, 9))                                        # last day Friday 9th: 7 working days
    assert s.employed_days == 7 and s.basic == e.money(D(3000) * 7 / 22)


def test_attendance_basis_pays_what_was_worked_plus_paid_leave():
    days = e.working_dates(*JAN, MON_FRI, set())
    att = {d: D(1) for d in days}
    att[days[0]] = D("0.5")                                                  # a half day
    del att[days[1]]                                                          # no attendance, no leave: absent
    del att[days[2]]                                                          # no attendance but approved paid leave
    s = run(attendance=att, paid_leave={days[2]: D(1)})
    assert s.payable_days == D("20.5") and s.absent_days == D("1.5") and s.paid_leave_days == 1
    ignore = run(paid_leave={days[2]: D(1)})                                  # the default basis ignores attendance entirely
    assert ignore.payable_days == 22 and ignore.absent_days == 0


def test_a_day_never_earns_more_than_one_credit():
    d = date(2026, 1, 5)
    assert run(attendance={d: D(3)}).payable_days == 1                       # nonsense input is capped at one day
    both = run(attendance={d: D("0.5")}, paid_leave={d: D("0.5")})
    assert both.payable_days == 1                                            # half worked + half paid leave = one day
    unpaid_half = run(attendance={d: D(1)}, unpaid_leave={d: D("0.5")})
    assert unpaid_half.payable_days == D("0.5")                              # unpaid half-day leave caps the credit


def test_earnings_and_deductions_with_the_three_calculations_and_caps():
    lines = [
        e.Line(comp("HRA", "earning", "percent_of_basic"), 4000),                       # 40% of basic
        e.Line(comp("TRANSPORT", "earning", "fixed"), 20000),                           # 200.00 fixed, prorated
        e.Line(comp("MEAL", "earning", "fixed", prorate=False), 5000),                  # 50.00 never prorated
        e.Line(comp("BONUSCAP", "earning", "percent_of_basic", cap_minor=10000), 5000), # 50% of basic but at most 100.00
        e.Line(comp("PF", "deduction", "percent_of_basic"), 1200),                      # 12% of basic
        e.Line(comp("INS", "deduction", "fixed"), 7500),                                # 75.00
        e.Line(comp("LEVY", "deduction", "percent_of_gross"), 100),                     # 1% of gross
        e.Line(comp("CAPPED", "deduction", "percent_of_gross", cap_minor=1000), 1000),  # 10% of gross but at most 10.00
    ]
    s = run(lines=lines)
    earn, ded = amounts(s, "earning"), amounts(s, "deduction")
    assert earn == {"BASIC": D("3000.00"), "HRA": D("1200.00"), "TRANSPORT": D("200.00"), "MEAL": D("50.00"), "BONUSCAP": D("100.00")}
    assert s.gross == D("4550.00")
    assert ded == {"PF": D("360.00"), "INS": D("75.00"), "LEVY": D("45.50"), "CAPPED": D("10.00")}
    assert s.deductions == D("490.50") and s.net == D("4059.50")
    assert next(l for l in s.lines if l.code == "BONUSCAP").basis.endswith("(capped)")


def test_proration_applies_to_fixed_earnings_but_not_where_switched_off():
    lines = [e.Line(comp("TRANSPORT", "earning", "fixed"), 22000), e.Line(comp("MEAL", "earning", "fixed", prorate=False), 22000)]
    s = run(lines=lines, unpaid_leave={date(2026, 1, 5): D(1), date(2026, 1, 6): D(1)})     # 20 of 22 days
    earn = amounts(s, "earning")
    assert earn["TRANSPORT"] == e.money(D(220) * 20 / 22) == D("200.00") and earn["MEAL"] == D("220.00")


def test_overtime_is_off_by_default_and_paid_at_the_hourly_rate_times_the_multiplier():
    assert "OVERTIME" not in amounts(run(overtime_minutes=600), "earning")
    s = run(overtime_minutes=150, overtime_multiplier=D("1.5"))              # 2.5 h; hourly = 3000 / (22 x 8)
    assert s.overtime_hours == D("2.5")
    pay = amounts(s, "earning")["OVERTIME"]
    assert pay == e.money(D(3000) / 176 * D("2.5") * D("1.5")) and s.gross == s.basic + pay


def test_deductions_larger_than_pay_are_flagged_not_hidden():
    s = run(lines=[e.Line(comp("ADVANCE", "deduction", "fixed"), 400000)])
    assert s.net == D("-1000.00") and s.warnings == ["deductions_exceed_pay"]


def test_adjustments_change_totals_and_the_warning_follows_the_net():
    s = run(lines=[e.Line(comp("ADVANCE", "deduction", "fixed"), 400000)])
    e.apply_adjustments(s, [("Correction", "earning", D("1200.00"))])
    assert s.gross == D("4200.00") and s.net == D("200.00") and s.warnings == []
    e.apply_adjustments(s, [("Recovery", "deduction", D("500"))])
    assert s.net == D("-300.00") and s.warnings == ["deductions_exceed_pay"]


def test_unknown_calculation_is_reported_and_skipped():
    s = run(lines=[e.Line(comp("ODD", "earning", "percent_of_gross"), 1000)])
    assert s.warnings == ["invalid_calc:ODD"] and s.gross == D("3000.00")


def test_a_period_with_no_working_days_pays_nothing_and_warns():
    s = e.compute(start=date(2026, 1, 10), end=date(2026, 1, 11), weekdays=MON_FRI, holidays=frozenset(), basic_minor=300000, lines=[])
    assert s.basic == 0 and "no_working_days" in s.warnings
