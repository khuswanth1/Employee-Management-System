"""Attendance calculations. Pure functions: no database, no clock (callers pass `now`), so every rule is unit-testable.

Conventions
* All stored instants are UTC. A *work date* is a calendar date in the employee's local timezone; for an overnight shift it is the
  date the shift STARTED on (a 22:00-06:00 shift that begins on Monday is Monday's work date even after midnight).
* Timezone = branch timezone, else the company timezone setting, else UTC. The working week and holidays come from the branch /
  company configuration; nothing assumes Monday to Friday.
* "Late" and "early departure" are measured against a fixed shift and only count once they exceed the grace period; they are
  then measured from the scheduled time (grace is a tolerance, not a discount). Flexible shifts have neither.
* Worked time = (check-out - check-in) minus the union of break intervals clipped to the session.
* Overtime: on a working day, time beyond `overtime_after_hours` (default: the required hours); on a weekend or holiday, all worked time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WORKING_DAYS = frozenset({0, 1, 2, 3, 4})  # Monday..Friday, only when nothing is configured
MAX_OPEN_HOURS = 16  # a session open longer than this has a missing check-out
STALE_AFTER_SHIFT_END_HOURS = 6


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ZoneInfo("UTC")


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def working_weekdays(days: list[str] | None) -> frozenset[int]:
    if not days:
        return DEFAULT_WORKING_DAYS
    out = {DAY_KEYS.index(d.lower()[:3]) for d in days if d and d.lower()[:3] in DAY_KEYS}
    return frozenset(out) or DEFAULT_WORKING_DAYS


@dataclass(frozen=True)
class ShiftRule:
    """`start`/`end` None = flexible shift (only the hours matter). end <= start means the shift crosses midnight."""
    start: time | None = None
    end: time | None = None
    grace_minutes: int = 0
    required_hours: float = 8.0
    half_day_hours: float | None = None
    overtime_after_hours: float | None = None

    @property
    def flexible(self) -> bool:
        return self.start is None or self.end is None

    @property
    def overnight(self) -> bool:
        return not self.flexible and self.end <= self.start

    @property
    def half_day(self) -> float:
        return self.half_day_hours if self.half_day_hours is not None else self.required_hours / 2

    @property
    def overtime_after(self) -> float:
        return self.overtime_after_hours if self.overtime_after_hours is not None else self.required_hours


@dataclass(frozen=True)
class Calendar:
    tz: ZoneInfo
    working_days: frozenset[int] = DEFAULT_WORKING_DAYS
    holidays: frozenset[date] = field(default_factory=frozenset)

    def day_type(self, d: date) -> str:
        if d in self.holidays:
            return "holiday"
        return "workday" if d.weekday() in self.working_days else "weekend"


def work_date_for(check_in: datetime, shift: ShiftRule | None, tz: ZoneInfo) -> date:
    """The work date a check-in belongs to. After midnight but before an overnight shift's end it is still yesterday's shift."""
    local = utc(check_in).astimezone(tz)
    if shift and shift.overnight and local.time() < shift.end:
        return local.date() - timedelta(days=1)
    return local.date()


def scheduled_window(work_date: date, shift: ShiftRule | None, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    """(start, end) of the shift as UTC instants, or None for flexible shifts. Built from local wall-clock times so DST is honoured."""
    if shift is None or shift.flexible:
        return None
    start = datetime.combine(work_date, shift.start, tzinfo=tz)
    end = datetime.combine(work_date + timedelta(days=1 if shift.overnight else 0), shift.end, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def merge_breaks(breaks: list[tuple[datetime, datetime | None]], lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    """Clip breaks to [lo, hi] (an open break ends at `hi`) and merge overlaps so nothing is subtracted twice."""
    spans = sorted((max(utc(s), lo), min(utc(e) if e else hi, hi)) for s, e in breaks)
    out: list[tuple[datetime, datetime]] = []
    for s, e in spans:
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


@dataclass(frozen=True)
class DayMetrics:
    worked_minutes: int
    break_minutes: int
    late_minutes: int
    early_minutes: int
    overtime_minutes: int
    day_type: str
    status: str  # in_progress | present | half_day | short_day | holiday_work | weekend_work

    @property
    def worked_hours(self) -> float:
        return round(self.worked_minutes / 60, 2)

    @property
    def overtime_hours(self) -> float:
        return round(self.overtime_minutes / 60, 2)


def _minutes(td: timedelta) -> int:
    return max(0, int(td.total_seconds() // 60))


def compute(check_in: datetime, check_out: datetime | None, breaks: list[tuple[datetime, datetime | None]], work_date: date,
            shift: ShiftRule | None, cal: Calendar, now: datetime) -> DayMetrics:
    """Metrics for one session. An open session (no check-out) is measured up to `now` and has status `in_progress`."""
    rule = shift or ShiftRule()
    start = utc(check_in)
    end = utc(check_out) if check_out else max(utc(now), start)
    brk = merge_breaks(breaks, start, end)
    break_min = sum(_minutes(e - s) for s, e in brk)
    worked = max(0, _minutes(end - start) - break_min)

    late = early = 0
    window = scheduled_window(work_date, rule, cal.tz)
    if window:
        grace = timedelta(minutes=rule.grace_minutes)
        if start > window[0] + grace:
            late = _minutes(start - window[0])
        if check_out and end < window[1] - grace:
            early = _minutes(window[1] - end)

    dtype = cal.day_type(work_date)
    overtime = worked if dtype != "workday" else max(0, worked - math.floor(rule.overtime_after * 60))
    if not check_out:
        status = "in_progress"
    elif dtype == "holiday":
        status = "holiday_work"
    elif dtype == "weekend":
        status = "weekend_work"
    elif worked >= rule.required_hours * 60:
        status = "present"
    elif worked >= rule.half_day * 60:
        status = "half_day"
    else:
        status = "short_day"
    return DayMetrics(worked, break_min, late, early, overtime, dtype, status)


def is_stale(check_in: datetime, work_date: date, shift: ShiftRule | None, tz: ZoneInfo, now: datetime) -> bool:
    """True when an open session has clearly been forgotten (missing check-out)."""
    if utc(now) - utc(check_in) > timedelta(hours=MAX_OPEN_HOURS):
        return True
    window = scheduled_window(work_date, shift, tz)
    return bool(window and utc(now) > window[1] + timedelta(hours=STALE_AFTER_SHIFT_END_HOURS))


def auto_close_time(check_in: datetime, work_date: date, shift: ShiftRule | None, tz: ZoneInfo) -> datetime:
    """Where a forgotten session is closed: the scheduled end (never before check-in), else check-in + required hours."""
    window = scheduled_window(work_date, shift, tz)
    start = utc(check_in)
    if window and window[1] > start:
        return window[1]
    return start + timedelta(hours=(shift.required_hours if shift else 8.0))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
