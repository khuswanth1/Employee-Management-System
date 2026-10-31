"""Leave calculations. Pure functions: no database, no clock.

* Days counted = days in the range that are working days for the person (their branch's week, not a fixed Mon-Fri) and not company
  holidays; a type may instead count every calendar day. A half day is 0.5 and only exists for a single day that would otherwise count.
* Accrual: `annual_upfront` grants the whole quota for the year; `monthly` grants quota/12 per month starting with the month the
  person joined, rounded so the twelve months add up to exactly the quota.
* Carry-forward moves at most `carry_max` unused days into the next year; carried days that are still unused at the end of the
  expiry month lapse (days taken up to then are assumed to use the carried days first).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

DEFAULT_WORKING_DAYS = frozenset({0, 1, 2, 3, 4})


def count_days(start: date, end: date, working_days: frozenset[int], holidays: frozenset[date] | set[date], *, half_day: str | None = None,
               count_all: bool = False) -> float:
    if end < start:
        return 0.0
    n, d = 0, start
    while d <= end:
        if count_all or (d.weekday() in working_days and d not in holidays):
            n += 1
        d += timedelta(days=1)
    if half_day:
        return 0.5 if (start == end and n == 1) else 0.0
    return float(n)


def overlaps(a_start: date, a_end: date, a_half: str | None, b_start: date, b_end: date, b_half: str | None) -> bool:
    """Do two requests clash? Two half days on the same date clash only if they are the same half."""
    if a_end < b_start or b_end < a_start:
        return False
    if a_half and b_half and a_start == a_end == b_start == b_end:
        return a_half == b_half
    return True


def _month_share(quota: float, month: int) -> float:
    return round(quota * month / 12, 2) - round(quota * (month - 1) / 12, 2)


def monthly_grants(quota: float, year: int, joined: date | None, as_of: date) -> list[tuple[str, float]]:
    """[(period 'YYYY-MM', days)] accrued up to and including `as_of`'s month, from the joining month on."""
    if as_of.year < year:
        return []
    last = 12 if as_of.year > year else as_of.month
    first = 1
    if joined is not None:
        if joined.year > year:
            return []
        if joined.year == year:
            first = joined.month
    return [(f"{year}-{m:02d}", round(_month_share(quota, m), 2)) for m in range(first, last + 1) if _month_share(quota, m)]


def carry_amount(remaining: float, carry_max: float) -> float:
    return round(max(0.0, min(remaining, carry_max)), 2)


def expiry_date(year: int, months: int) -> date:
    """Last day of month `months` (1-12) of `year`: carried days not used by then lapse."""
    m = max(1, min(12, months))
    return date(year, m, calendar.monthrange(year, m)[1])


def carried_to_expire(carried_in: float, used_by_start: list[tuple[date, float]], expires_on: date, remaining_now: float) -> float:
    """Carried days still unused at `expires_on`, never more than what is actually left in the balance."""
    used_before = sum(days for start, days in used_by_start if start <= expires_on)
    return round(max(0.0, min(carried_in - used_before, remaining_now)), 2)
