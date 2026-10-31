"""Leave calculations: pure-function tests."""
from datetime import date

from app.modules.leave import engine as e

MON_FRI = frozenset({0, 1, 2, 3, 4})
SUN_THU = frozenset({6, 0, 1, 2, 3})
# 2026-01-05 is a Monday.


def test_counts_working_days_and_skips_weekends_and_holidays():
    assert e.count_days(date(2026, 1, 5), date(2026, 1, 11), MON_FRI, set()) == 5
    assert e.count_days(date(2026, 1, 5), date(2026, 1, 11), MON_FRI, {date(2026, 1, 6)}) == 4
    assert e.count_days(date(2026, 1, 10), date(2026, 1, 11), MON_FRI, set()) == 0      # a weekend only
    assert e.count_days(date(2026, 1, 11), date(2026, 1, 5), MON_FRI, set()) == 0       # reversed range


def test_the_working_week_is_the_persons_not_a_fixed_one():
    # Sun-Thu branch: Sunday counts, Friday and Saturday do not
    assert e.count_days(date(2026, 1, 4), date(2026, 1, 10), SUN_THU, set()) == 5
    assert e.count_days(date(2026, 1, 9), date(2026, 1, 10), SUN_THU, set()) == 0
    assert e.count_days(date(2026, 1, 11), date(2026, 1, 11), SUN_THU, set()) == 1


def test_types_can_count_every_calendar_day():
    assert e.count_days(date(2026, 1, 5), date(2026, 1, 11), MON_FRI, {date(2026, 1, 6)}, count_all=True) == 7


def test_half_days():
    mon = date(2026, 1, 5)
    assert e.count_days(mon, mon, MON_FRI, set(), half_day="first") == 0.5
    assert e.count_days(date(2026, 1, 10), date(2026, 1, 10), MON_FRI, set(), half_day="second") == 0.0   # Saturday: nothing to take
    assert e.count_days(mon, mon, MON_FRI, {mon}, half_day="first") == 0.0                               # a holiday
    assert e.count_days(mon, date(2026, 1, 6), MON_FRI, set(), half_day="first") == 0.0                  # half days are single-day only


def test_overlap_rules_including_two_half_days():
    d = date(2026, 1, 5)
    assert e.overlaps(d, d, "first", d, d, "second") is False
    assert e.overlaps(d, d, "first", d, d, "first") is True
    assert e.overlaps(d, d, "first", d, d, None) is True                        # a half day inside a full day
    assert e.overlaps(d, date(2026, 1, 7), None, date(2026, 1, 7), date(2026, 1, 9), None) is True
    assert e.overlaps(d, date(2026, 1, 6), None, date(2026, 1, 7), date(2026, 1, 9), None) is False
    assert e.overlaps(d, date(2026, 1, 7), None, date(2026, 1, 7), date(2026, 1, 7), "second") is True


def test_monthly_accrual_adds_up_to_the_quota_exactly():
    grants = e.monthly_grants(20, 2026, None, date(2026, 12, 31))
    assert [p for p, _ in grants] == [f"2026-{m:02d}" for m in range(1, 13)]
    assert round(sum(d for _, d in grants), 2) == 20
    assert round(sum(d for _, d in e.monthly_grants(21, 2026, None, date(2026, 12, 1))), 2) == 21
    assert all(d > 0 for _, d in grants)


def test_monthly_accrual_stops_at_the_current_month_and_starts_at_joining():
    assert [p for p, _ in e.monthly_grants(18, 2026, None, date(2026, 3, 15))] == ["2026-01", "2026-02", "2026-03"]
    assert round(sum(d for _, d in e.monthly_grants(18, 2026, None, date(2026, 3, 15))), 2) == 4.5
    joined = e.monthly_grants(18, 2026, date(2026, 7, 20), date(2026, 9, 1))
    assert [p for p, _ in joined] == ["2026-07", "2026-08", "2026-09"] and round(sum(d for _, d in joined), 2) == 4.5
    assert e.monthly_grants(18, 2026, date(2027, 1, 1), date(2026, 12, 1)) == []              # not employed yet
    assert e.monthly_grants(18, 2027, None, date(2026, 12, 31)) == []                         # a future year has not accrued
    assert len(e.monthly_grants(18, 2025, date(2020, 1, 1), date(2026, 2, 1))) == 12          # a past year is complete


def test_carry_forward_is_capped_and_never_negative():
    assert e.carry_amount(7.5, 5) == 5
    assert e.carry_amount(3, 5) == 3
    assert e.carry_amount(-2, 5) == 0
    assert e.carry_amount(9, 0) == 0


def test_expiry_date_is_the_end_of_the_named_month():
    assert e.expiry_date(2026, 3) == date(2026, 3, 31)
    assert e.expiry_date(2028, 2) == date(2028, 2, 29)
    assert e.expiry_date(2026, 99) == date(2026, 12, 31)


def test_unused_carried_days_lapse_but_used_ones_do_not():
    exp = date(2026, 3, 31)
    assert e.carried_to_expire(5, [], exp, remaining_now=12) == 5
    assert e.carried_to_expire(5, [(date(2026, 2, 2), 2)], exp, remaining_now=10) == 3             # 2 carried days were taken
    assert e.carried_to_expire(5, [(date(2026, 2, 2), 6)], exp, remaining_now=9) == 0              # all consumed
    assert e.carried_to_expire(5, [(date(2026, 6, 1), 4)], exp, remaining_now=11) == 5             # leave after the expiry date doesn't help
    assert e.carried_to_expire(5, [], exp, remaining_now=2) == 2                                    # cannot expire more than is left
