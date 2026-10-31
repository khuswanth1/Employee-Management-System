"""Attendance calculations: pure-function tests, no database."""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.modules.attendance import engine as e

UTC = timezone.utc
IST = e.zone("Asia/Kolkata")
LON = e.zone("Europe/London")
DAY = e.ShiftRule(start=time(9), end=time(18), grace_minutes=10, required_hours=8)
NIGHT = e.ShiftRule(start=time(22), end=time(6), grace_minutes=10, required_hours=8)
MON_FRI = e.Calendar(e.zone("UTC"))


def at(y, m, d, hh=0, mm=0, tz=UTC):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def run(cin, cout, breaks=(), shift=DAY, cal=MON_FRI, work_date=None, now=None):
    wd = work_date or e.work_date_for(cin, shift, cal.tz)
    return e.compute(cin, cout, list(breaks), wd, shift, cal, now or (cout or cin))


# 2026-01-05 is a Monday, 2026-01-10 a Saturday, 2026-01-11 a Sunday.

def test_normal_day_with_a_break():
    m = run(at(2026, 1, 5, 9), at(2026, 1, 5, 18), [(at(2026, 1, 5, 12), at(2026, 1, 5, 13))])
    assert (m.worked_minutes, m.break_minutes, m.late_minutes, m.early_minutes, m.overtime_minutes) == (480, 60, 0, 0, 0)
    assert m.status == "present" and m.day_type == "workday"


@pytest.mark.parametrize("minute,late", [(0, 0), (10, 0), (11, 11), (45, 45)])
def test_late_arrival_counts_only_beyond_grace_and_from_the_scheduled_start(minute, late):
    assert run(at(2026, 1, 5, 9, minute), at(2026, 1, 5, 18)).late_minutes == late


@pytest.mark.parametrize("out,early", [((18, 0), 0), ((17, 50), 0), ((17, 49), 11), ((16, 0), 120)])
def test_early_departure_counts_only_beyond_grace(out, early):
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, *out)).early_minutes == early


def test_overtime_beyond_required_hours_on_a_working_day():
    m = run(at(2026, 1, 5, 9), at(2026, 1, 5, 20))
    assert m.worked_minutes == 660 and m.overtime_minutes == 180 and m.overtime_hours == 3.0
    m = run(at(2026, 1, 5, 9), at(2026, 1, 5, 20), shift=e.ShiftRule(start=time(9), end=time(18), required_hours=8, overtime_after_hours=9))
    assert m.overtime_minutes == 120  # custom threshold


def test_half_day_and_short_day_thresholds():
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 13, 30)).status == "half_day"   # 4.5 h
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 13)).status == "half_day"        # exactly 4 h
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 12, 59)).status == "short_day"
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 17)).status == "present"          # exactly 8 h
    custom = e.ShiftRule(required_hours=6, half_day_hours=2)
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 11), shift=custom).status == "half_day"


def test_weekend_and_holiday_work_is_all_overtime():
    sat = run(at(2026, 1, 10, 10), at(2026, 1, 10, 14))
    assert sat.day_type == "weekend" and sat.status == "weekend_work" and sat.overtime_minutes == 240
    cal = e.Calendar(e.zone("UTC"), holidays=frozenset({date(2026, 1, 5)}))
    hol = run(at(2026, 1, 5, 9), at(2026, 1, 5, 17), cal=cal)
    assert hol.day_type == "holiday" and hol.status == "holiday_work" and hol.overtime_minutes == 480


def test_the_working_week_is_configurable():
    sun_thu = e.Calendar(e.zone("UTC"), e.working_weekdays(["sun", "mon", "tue", "wed", "thu"]))
    assert sun_thu.day_type(date(2026, 1, 11)) == "workday"   # Sunday
    assert sun_thu.day_type(date(2026, 1, 9)) == "weekend"    # Friday
    assert e.working_weekdays(None) == e.DEFAULT_WORKING_DAYS == e.working_weekdays([])
    assert e.working_weekdays(["Saturday", "bogus"]) == frozenset({5})
    six_days = e.Calendar(e.zone("UTC"), e.working_weekdays(["mon", "tue", "wed", "thu", "fri", "sat"]))
    assert run(at(2026, 1, 10, 9), at(2026, 1, 10, 17), cal=six_days).status == "present"


def test_flexible_shift_has_no_lateness_only_hours():
    flex = e.ShiftRule(required_hours=7)
    m = run(at(2026, 1, 5, 13), at(2026, 1, 5, 21), shift=flex)
    assert m.late_minutes == m.early_minutes == 0 and m.status == "present" and m.overtime_minutes == 60
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 17), shift=None).status == "present"  # no shift assigned: 8 h default


def test_breaks_are_merged_clipped_and_open_breaks_end_at_check_out():
    b = [(at(2026, 1, 5, 12), at(2026, 1, 5, 12, 30)), (at(2026, 1, 5, 12, 15), at(2026, 1, 5, 13)),   # overlap -> 60 min
         (at(2026, 1, 5, 15), at(2026, 1, 5, 15, 10)),
         (at(2026, 1, 5, 8, 30), at(2026, 1, 5, 9, 30)),                                              # starts before check-in
         (at(2026, 1, 5, 17, 50), None)]                                                              # forgotten open break
    m = run(at(2026, 1, 5, 9), at(2026, 1, 5, 18), b)
    assert m.break_minutes == 30 + 60 + 10 + 10 and m.worked_minutes == 540 - 110
    assert run(at(2026, 1, 5, 9), at(2026, 1, 5, 18), [(at(2026, 1, 5, 20), at(2026, 1, 5, 21))]).break_minutes == 0


def test_open_session_is_measured_up_to_now():
    m = run(at(2026, 1, 5, 9), None, [(at(2026, 1, 5, 12), None)], now=at(2026, 1, 5, 12, 30))
    assert m.status == "in_progress" and m.worked_minutes == 180 and m.break_minutes == 30 and m.early_minutes == 0


# --------------------------------------------------------------- timezones and overnight shifts

def test_work_date_follows_the_local_calendar_not_utc():
    flex = e.ShiftRule()
    assert e.work_date_for(at(2026, 3, 2, 23, 30), flex, IST) == date(2026, 3, 3)           # 05:00 next day in Kolkata
    assert e.work_date_for(at(2026, 3, 2, 3, 30), flex, e.zone("America/New_York")) == date(2026, 3, 1)
    assert e.work_date_for(at(2026, 3, 2, 3, 30), flex, e.zone("not/a-zone")) == date(2026, 3, 2)  # bad name -> UTC


def test_overnight_shift_belongs_to_the_day_it_started():
    mon_2205 = at(2026, 1, 5, 22, 5, IST)
    after_midnight = at(2026, 1, 6, 1, 0, IST)       # a late arrival, still Monday's shift
    next_morning = at(2026, 1, 6, 8, 0, IST)
    assert e.work_date_for(mon_2205, NIGHT, IST) == date(2026, 1, 5)
    assert e.work_date_for(after_midnight, NIGHT, IST) == date(2026, 1, 5)
    assert e.work_date_for(next_morning, NIGHT, IST) == date(2026, 1, 6)


def test_cross_midnight_session_is_one_record_with_correct_totals():
    cal = e.Calendar(IST)
    cin, cout = at(2026, 1, 5, 22, 0, IST), at(2026, 1, 6, 6, 0, IST)
    m = e.compute(cin, cout, [(at(2026, 1, 6, 1, 0, IST), at(2026, 1, 6, 1, 30, IST))], date(2026, 1, 5), NIGHT, cal, cout)
    assert m.worked_minutes == 450 and m.break_minutes == 30 and m.late_minutes == 0 and m.early_minutes == 0
    assert m.status == "half_day"  # 7.5 h worked of 8 h required


def test_night_shift_on_friday_is_friday_work_even_though_it_ends_on_saturday():
    cal = e.Calendar(IST)
    cin, cout = at(2026, 1, 9, 22, 0, IST), at(2026, 1, 10, 6, 0, IST)
    m = e.compute(cin, cout, [], date(2026, 1, 9), NIGHT, cal, cout)
    assert m.day_type == "workday" and m.status == "present" and m.overtime_minutes == 0


def test_late_arrival_on_an_overnight_shift():
    cal = e.Calendar(IST)
    m = e.compute(at(2026, 1, 5, 23, 30, IST), at(2026, 1, 6, 6, 0, IST), [], date(2026, 1, 5), NIGHT, cal, at(2026, 1, 6, 6, 0, IST))
    assert m.late_minutes == 90


def test_scheduled_window_honours_daylight_saving_time():
    s, en = e.scheduled_window(date(2026, 3, 28), DAY, LON)        # GMT
    assert (s, en) == (at(2026, 3, 28, 9), at(2026, 3, 28, 18))
    s, en = e.scheduled_window(date(2026, 3, 29), DAY, LON)        # BST starts that night: 09:00 local is 08:00Z
    assert (s, en) == (at(2026, 3, 29, 8), at(2026, 3, 29, 17))
    s, en = e.scheduled_window(date(2026, 3, 28), NIGHT, LON)      # the night the clocks jump: a 22:00-06:00 shift is 7 real hours
    assert en - s == timedelta(hours=7)
    assert e.scheduled_window(date(2026, 3, 28), e.ShiftRule(), LON) is None


# ------------------------------------------------------------------- missing check-out

def test_stale_sessions_are_detected():
    cin = at(2026, 1, 5, 9)
    assert not e.is_stale(cin, date(2026, 1, 5), DAY, e.zone("UTC"), at(2026, 1, 5, 20))
    assert e.is_stale(cin, date(2026, 1, 5), DAY, e.zone("UTC"), at(2026, 1, 6, 0, 1))            # 6 h after the shift end
    assert not e.is_stale(cin, date(2026, 1, 5), e.ShiftRule(), e.zone("UTC"), at(2026, 1, 5, 23))  # flexible, 14 h
    assert e.is_stale(cin, date(2026, 1, 5), e.ShiftRule(), e.zone("UTC"), at(2026, 1, 6, 2))       # flexible, 17 h
    # an overnight session that is simply in progress at 03:00 is not stale
    assert not e.is_stale(at(2026, 1, 5, 22, 0, IST), date(2026, 1, 5), NIGHT, IST, at(2026, 1, 6, 3, 0, IST))


def test_auto_close_time():
    assert e.auto_close_time(at(2026, 1, 5, 9), date(2026, 1, 5), DAY, e.zone("UTC")) == at(2026, 1, 5, 18)
    assert e.auto_close_time(at(2026, 1, 5, 9), date(2026, 1, 5), e.ShiftRule(required_hours=6), e.zone("UTC")) == at(2026, 1, 5, 15)
    assert e.auto_close_time(at(2026, 1, 5, 19), date(2026, 1, 5), DAY, e.zone("UTC")) == at(2026, 1, 6, 3)  # arrived after the shift ended
    assert e.auto_close_time(at(2026, 1, 5, 22, 0, IST), date(2026, 1, 5), NIGHT, IST) == at(2026, 1, 6, 6, 0, IST)


def test_naive_datetimes_from_sqlite_are_treated_as_utc():
    naive_in, naive_out = datetime(2026, 1, 5, 9), datetime(2026, 1, 5, 17)
    assert run(naive_in, naive_out).worked_minutes == 480


def test_haversine_distance():
    assert e.haversine_m(12.9716, 77.5946, 12.9716, 77.5946) == 0
    assert 110 < e.haversine_m(12.0, 77.0, 12.001, 77.0) < 112
    assert 9_000 < e.haversine_m(12.9716, 77.5946, 12.9716 + 0.09, 77.5946) < 11_000
