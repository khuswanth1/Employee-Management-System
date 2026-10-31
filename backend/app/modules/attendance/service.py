"""Attendance service layer: resolves each person's timezone / working week / shift / holidays and applies the pure engine."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import get_setting
from app.db.base import as_utc, utcnow
from app.db.tenant_models import Attendance, Branch, Holiday, Shift, User
from app.modules.attendance import engine as eng


def rule_of(shift: Shift | None, default_hours: float) -> eng.ShiftRule:
    if shift is None:
        return eng.ShiftRule(required_hours=default_hours)
    return eng.ShiftRule(start=shift.start_time, end=shift.end_time, grace_minutes=shift.grace_minutes or 0,
                         required_hours=shift.required_hours or default_hours, half_day_hours=shift.half_day_hours,
                         overtime_after_hours=shift.overtime_after_hours)


class Resolver:
    """Loads the small configuration tables once per request."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.branches = {b.id: b for b in db.scalars(select(Branch))}
        self.shifts = {s.id: s for s in db.scalars(select(Shift))}
        self.holidays = frozenset(h.date for h in db.scalars(select(Holiday)))
        self.company_tz = get_setting(db, "company_timezone", "UTC").strip() or "UTC"
        try:
            self.std_hours = float(get_setting(db, "standard_work_hours", "8"))
        except ValueError:
            self.std_hours = 8.0
        self.allow_wfh = get_setting(db, "allow_wfh", "true").lower() != "false"

    def branch_of(self, user: User) -> Branch | None:
        return self.branches.get(user.branch_id) if user.branch_id else None

    def calendar(self, user: User) -> eng.Calendar:
        b = self.branch_of(user)
        return eng.Calendar(eng.zone((b.timezone if b and b.timezone else None) or self.company_tz),
                            eng.working_weekdays(b.working_days if b else None), self.holidays)

    def shift_for(self, shift_id: int | None) -> Shift | None:
        return self.shifts.get(shift_id) if shift_id else None

    def rule(self, shift_id: int | None) -> eng.ShiftRule:
        return rule_of(self.shift_for(shift_id), self.std_hours)


def open_session(db: Session, user_id: int) -> Attendance | None:
    return db.scalar(select(Attendance).where(Attendance.user_id == user_id, Attendance.check_out.is_(None)).order_by(Attendance.check_in.desc()))


def metrics_for(a: Attendance, user: User, res: Resolver, now: datetime | None = None) -> eng.DayMetrics:
    cal = res.calendar(user)
    return eng.compute(a.check_in, a.check_out, [(b.start, b.end) for b in a.breaks], a.work_date, res.rule(a.shift_id), cal, now or utcnow())


def finalize(a: Attendance, user: User, res: Resolver) -> None:
    """Freeze the day's numbers on the record. Later edits to shifts, holidays or the working week do not touch them."""
    m = metrics_for(a, user, res)
    a.status, a.day_type = m.status, m.day_type
    a.worked_minutes, a.break_minutes = m.worked_minutes, m.break_minutes
    a.late_minutes, a.early_minutes, a.overtime_minutes = m.late_minutes, m.early_minutes, m.overtime_minutes


def stale(a: Attendance, user: User, res: Resolver, now: datetime) -> bool:
    cal = res.calendar(user)
    return eng.is_stale(a.check_in, a.work_date, res.shift_for(a.shift_id) and res.rule(a.shift_id), cal.tz, now)


def auto_close(a: Attendance, user: User, res: Resolver) -> None:
    """Close a forgotten session at the scheduled end (or check-in + required hours) and mark it so reports can flag it."""
    cal = res.calendar(user)
    rule = res.rule(a.shift_id)
    end = eng.auto_close_time(a.check_in, a.work_date, rule, cal.tz)
    for b in a.breaks:
        if b.end is None:
            b.end = max(end, as_utc(b.start))
    a.check_out, a.auto_closed = end, True
    finalize(a, user, res)


def view(a: Attendance, user: User | None, res: Resolver, name: str | None = None, now: datetime | None = None) -> dict:
    """API shape. Closed sessions use their frozen numbers; open and pre-feature ones are computed live."""
    now = now or utcnow()
    if a.check_out is not None and a.worked_minutes is not None:
        worked, brk, late, early, ot = a.worked_minutes, a.break_minutes or 0, a.late_minutes or 0, a.early_minutes or 0, a.overtime_minutes or 0
        status, dtype = a.status, a.day_type
    elif user is not None:
        m = metrics_for(a, user, res, now)
        worked, brk, late, early, ot, status, dtype = m.worked_minutes, m.break_minutes, m.late_minutes, m.early_minutes, m.overtime_minutes, m.status, m.day_type
    else:
        worked = brk = late = early = ot = 0
        status = dtype = None
    shift = res.shift_for(a.shift_id)
    return {
        "id": a.id, "user_id": a.user_id, "user_name": name, "work_date": a.work_date, "check_in": a.check_in, "check_out": a.check_out,
        "on_break": a.check_out is None and any(b.end is None for b in a.breaks),
        "breaks": [{"start": b.start, "end": b.end} for b in a.breaks],
        "worked_hours": round(worked / 60, 2), "break_minutes": brk, "overtime_hours": round(ot / 60, 2),
        "late_minutes": late, "early_minutes": early, "overtime_minutes": ot, "status": status, "day_type": dtype,
        "work_mode": a.work_mode, "source": a.source, "auto_closed": a.auto_closed,
        "shift": {"id": shift.id, "name": shift.name} if shift else None,
        "timezone": str(res.calendar(user).tz) if user is not None else None,  # the zone the times should be shown in
    }


def default_window(res: Resolver, user: User, today: date | None = None) -> date:
    """Today's date in the person's own timezone."""
    return datetime.now(res.calendar(user).tz).date() if today is None else today


def local_to_utc(dt: datetime, tz) -> datetime:
    """Naive datetimes (from a datetime-local input) are wall-clock times in `tz`; aware ones are converted."""
    return dt.replace(tzinfo=tz).astimezone(eng.timezone.utc) if dt.tzinfo is None else dt.astimezone(eng.timezone.utc)


def days_ago(n: int) -> date:
    return utcnow().date() - timedelta(days=n)
