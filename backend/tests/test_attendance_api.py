"""Attendance through the API: timezones, shifts, overnight work, missing check-outs, geo-fence, corrections, reports, isolation."""
from datetime import datetime, timezone

import pytest

from app.modules.attendance import corrections as corr_mod
from app.modules.attendance import router as att_router
from app.modules.attendance import service as att_svc
from tests.conftest import PW

UTC = timezone.utc
# 2026-01-05 is a Monday. Kolkata is UTC+5:30 (no DST).


def z(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


class Clock:
    now = z(2026, 1, 5, 4)

    def set(self, dt):
        Clock.now = dt


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    for mod in (att_router, corr_mod, att_svc):
        monkeypatch.setattr(mod, "utcnow", lambda: Clock.now)
    return c


@pytest.fixture(scope="module")
def co(api):
    """Company with an Indian branch whose working week is Sunday-Thursday, plus people with and without a branch."""
    api.make_company("attco")
    f = api.login("attco", "founder@attco.com")
    branch = api.post(f, "/branches", {"name": "Kolkata", "code": "KOL", "timezone": "Asia/Kolkata", "working_days": ["sun", "mon", "tue", "wed", "thu"]}).json()
    hr = api.add_user(f, "hr@attco.com", "hr")
    mgr = api.add_user(f, "mgr@attco.com", "manager")
    mgr2 = api.add_user(f, "mgr2@attco.com", "manager")
    people = {n: api.add_user(f, f"{n}@attco.com", "employee", manager_id=mgr["id"]) for n in ("in1", "in2", "in3", "in4", "in5", "in6", "in7", "in8", "in9")}
    free = api.add_user(f, "free@attco.com", "employee")
    other = api.add_user(f, "other@attco.com", "employee", manager_id=mgr2["id"])
    ids = [hr["id"], mgr["id"], mgr2["id"], *[p["id"] for p in people.values()], other["id"]]
    assert api.post(f, f"/branches/{branch['id']}/members", {"user_ids": ids}).status_code == 200
    tok = {n: api.login("attco", f"{n}@attco.com") for n in (*people, "free", "other", "hr", "mgr", "mgr2")}
    return {"f": f, "branch": branch["id"], "tok": tok, "ids": {**{n: p["id"] for n, p in people.items()}, "free": free["id"], "other": other["id"],
                                                                 "hr": hr["id"], "mgr": mgr["id"], "mgr2": mgr2["id"]}}


def _in(api, co, who, **body):
    return api.post(co["tok"][who], "/attendance/check-in", body or None)


# -------------------------------------------------------------------- timezones & working week

def test_work_date_and_weekend_follow_the_branch_timezone_and_week(api, co, clock):
    clock.set(z(2026, 1, 8, 20, 0))                      # Thu 20:00Z = Fri 01:30 IST -> a weekend day for this branch
    r = _in(api, co, "in1")
    assert r.status_code == 201 and r.json()["work_date"] == "2026-01-09" and r.json()["day_type"] == "weekend"
    clock.set(z(2026, 1, 8, 23, 30))
    out = api.post(co["tok"]["in1"], "/attendance/check-out").json()
    assert out["day_type"] == "weekend" and out["status"] == "weekend_work" and out["overtime_minutes"] == 210 and out["worked_hours"] == 3.5
    assert api.get(co["tok"]["in1"], "/attendance/today").json()["timezone"] == "Asia/Kolkata"
    assert api.get(co["tok"]["in1"], "/attendance/mine?start=2026-01-01").json()["items"][0]["timezone"] == "Asia/Kolkata"


def test_sunday_is_a_working_day_here_but_not_for_a_branchless_user(api, co, clock):
    clock.set(z(2026, 1, 11, 3, 0))                      # Sunday 08:30 IST
    assert _in(api, co, "in2").json()["work_date"] == "2026-01-11"
    clock.set(z(2026, 1, 11, 12, 0))
    assert api.post(co["tok"]["in2"], "/attendance/check-out").json()["day_type"] == "workday"
    clock.set(z(2026, 1, 11, 3, 0))
    free = api.post(co["tok"]["free"], "/attendance/check-in").json()
    clock.set(z(2026, 1, 11, 12, 0))
    assert api.post(co["tok"]["free"], "/attendance/check-out").json()["day_type"] == "weekend"  # default Mon-Fri, UTC
    assert free["work_date"] == "2026-01-11"


def test_company_timezone_setting_applies_to_people_without_a_branch(api, co, clock):
    assert api.put(co["f"], "/admin/settings/company_timezone", {"value": "Pacific/Auckland"}).status_code == 200
    try:
        clock.set(z(2026, 1, 12, 20, 0))                 # 09:00 Tuesday in Auckland (UTC+13 in January)
        assert api.post(co["tok"]["free"], "/attendance/check-in").json()["work_date"] == "2026-01-13"
    finally:
        api.put(co["f"], "/admin/settings/company_timezone", {"value": "UTC"})
    assert api.put(co["f"], "/admin/settings/company_timezone", {"value": "Mars/Olympus"}).status_code in (400, 422)


def test_holiday_work_is_flagged(api, co, clock):
    assert api.post(co["f"], "/leave/holidays", {"name": "Founders day", "date": "2026-01-14"}).status_code == 201   # a Wednesday
    clock.set(z(2026, 1, 14, 4, 0))
    _in(api, co, "in3")
    clock.set(z(2026, 1, 14, 10, 0))
    out = api.post(co["tok"]["in3"], "/attendance/check-out").json()
    assert out["day_type"] == "holiday" and out["status"] == "holiday_work" and out["overtime_minutes"] == 360


# ------------------------------------------------------------------------------- work mode

def test_work_from_home_can_be_switched_off(api, co, clock):
    clock.set(z(2026, 1, 15, 4, 0))
    assert api.put(co["f"], "/admin/settings/allow_wfh", {"value": "false"}).status_code == 200
    try:
        assert _in(api, co, "in4", work_mode="wfh").status_code == 403
    finally:
        api.put(co["f"], "/admin/settings/allow_wfh", {"value": "true"})
    r = _in(api, co, "in4", work_mode="wfh", lat=1.0, lng=2.0)
    assert r.status_code == 201 and r.json()["work_mode"] == "wfh"
    assert api.post(co["tok"]["in4"], "/attendance/check-in", {"work_mode": "teleport"}).status_code == 422


# ------------------------------------------------------------------------------------ shifts

def test_shift_validation_and_permissions(api, co):
    hr, emp, mgr = co["tok"]["hr"], co["tok"]["in5"], co["tok"]["mgr"]
    ok = {"name": "General", "start_time": "09:00", "end_time": "18:00", "grace_minutes": 10, "required_hours": 8}
    assert api.post(emp, "/attendance/shifts", ok).status_code == 403
    assert api.post(mgr, "/attendance/shifts", ok).status_code == 403
    assert api.post(hr, "/attendance/shifts", {**ok, "end_time": None}).status_code == 422          # start without end
    assert api.post(hr, "/attendance/shifts", {**ok, "end_time": "09:00"}).status_code == 422       # zero length
    assert api.post(hr, "/attendance/shifts", {**ok, "half_day_hours": 9}).status_code == 422
    assert api.post(hr, "/attendance/shifts", {**ok, "grace_minutes": 500}).status_code == 422
    made = api.post(hr, "/attendance/shifts", ok)
    assert made.status_code == 201 and made.json()["overnight"] is False
    assert api.post(hr, "/attendance/shifts", {**ok, "name": "general"}).status_code == 409           # names are unique, case-insensitive
    assert api.get(mgr, "/attendance/shifts").status_code == 200 and api.get(emp, "/attendance/shifts").status_code == 403
    sid = made.json()["id"]
    assert api.patch(hr, f"/attendance/shifts/{sid}", {"end_time": None}).status_code == 422        # would leave a start without an end
    night = api.post(hr, "/attendance/shifts", {"name": "Night", "start_time": "22:00", "end_time": "06:00"}).json()
    assert night["overnight"] is True and night["required_hours"] == 8
    flex = api.post(hr, "/attendance/shifts", {"name": "Flexi", "required_hours": 6}).json()
    assert flex["flexible"] is True


def test_assignment_is_scoped_and_only_affects_future_sessions(api, co, clock):
    hr, f = co["tok"]["hr"], co["f"]
    sid = api.post(hr, "/attendance/shifts", {"name": "Late shift", "start_time": "09:00", "end_time": "18:00", "grace_minutes": 10}).json()["id"]
    # out of scope for a branch HR: nobody without a branch
    assert api.post(hr, "/attendance/shift-assignments", {"shift_id": sid, "user_ids": [co["ids"]["free"]]}).status_code == 404
    assert api.post(hr, "/attendance/shift-assignments", {"shift_id": sid, "user_ids": [co["ids"]["in6"], 999999]}).status_code == 404
    assert api.post(hr, "/attendance/shift-assignments", {"shift_id": sid, "user_ids": [co["ids"]["in6"]]}).json() == {"updated": 1}
    # a day worked under the shift
    clock.set(z(2026, 1, 19, 3, 55))                        # Mon 09:25 IST -> 25 min late
    _in(api, co, "in6")
    clock.set(z(2026, 1, 19, 11, 30))                       # 17:00 IST -> 60 min early
    out = api.post(co["tok"]["in6"], "/attendance/check-out").json()
    assert (out["late_minutes"], out["early_minutes"], out["status"], out["shift"]["name"]) == (25, 60, "half_day", "Late shift")
    # edit the shift afterwards: the recorded day keeps its numbers
    assert api.patch(hr, f"/attendance/shifts/{sid}", {"start_time": "07:00", "end_time": "15:00", "required_hours": 6}).status_code == 200
    again = [a for a in api.get(co["tok"]["in6"], "/attendance/mine?start=2026-01-19").json()["items"] if a["work_date"] == "2026-01-19"][0]
    assert (again["late_minutes"], again["early_minutes"], again["status"]) == (25, 60, "half_day")
    assert api.delete(hr, f"/attendance/shifts/{sid}").status_code == 409                         # assigned and used
    assert api.post(hr, "/attendance/shift-assignments", {"shift_id": None, "user_ids": [co["ids"]["in6"]]}).json() == {"updated": 1}
    assert api.patch(hr, f"/attendance/shifts/{sid}", {"is_active": False}).json()["is_active"] is False
    assert api.post(hr, "/attendance/shift-assignments", {"shift_id": sid, "user_ids": [co["ids"]["in6"]]}).status_code == 400  # inactive
    assert api.get(f, "/attendance/shifts").json()["items"]


def test_overnight_shift_is_one_session_across_midnight(api, co, clock):
    hr, tok = co["tok"]["hr"], co["tok"]["in7"]
    night = api.post(hr, "/attendance/shifts", {"name": "Night shift", "start_time": "22:00", "end_time": "06:00", "grace_minutes": 10}).json()["id"]
    api.post(hr, "/attendance/shift-assignments", {"shift_id": night, "user_ids": [co["ids"]["in7"]]})
    clock.set(z(2026, 2, 2, 16, 30))                        # Mon 22:00 IST
    first = api.post(tok, "/attendance/check-in").json()
    assert first["work_date"] == "2026-02-02" and first["late_minutes"] == 0
    clock.set(z(2026, 2, 2, 20, 0))                         # Tue 01:30 IST: already past midnight
    assert api.post(tok, "/attendance/break/start").status_code == 200
    today = api.get(tok, "/attendance/today").json()["record"]
    assert today["id"] == first["id"] and today["on_break"] is True            # still yesterday's session, found after midnight
    assert api.post(tok, "/attendance/check-in").status_code == 409            # a duplicate check-in after midnight is refused
    clock.set(z(2026, 2, 2, 20, 30))
    assert api.post(tok, "/attendance/break/end").status_code == 200
    clock.set(z(2026, 2, 3, 0, 35))                         # Tue 06:05 IST
    out = api.post(tok, "/attendance/check-out").json()
    assert out["work_date"] == "2026-02-02" and out["break_minutes"] == 30 and out["worked_hours"] == 7.58
    assert out["early_minutes"] == 0 and out["status"] == "half_day"            # 7 h 35 m worked of 8 h
    mine = api.get(tok, "/attendance/mine?start=2026-02-01").json()
    assert mine["total"] == 1                                                    # one record, not two
    clock.set(z(2026, 2, 3, 2, 30))                         # Tue 08:00 IST: the next day's work
    again = api.post(tok, "/attendance/check-in")
    assert again.status_code == 201 and again.json()["work_date"] == "2026-02-03"


# ------------------------------------------------------------- duplicates and missing check-out

def test_second_check_in_on_a_finished_day_is_refused(api, co, clock):
    clock.set(z(2026, 2, 9, 4, 0))
    tok = co["tok"]["in8"]
    assert api.post(tok, "/attendance/check-in").status_code == 201
    assert api.post(tok, "/attendance/check-in").status_code == 409
    clock.set(z(2026, 2, 9, 10, 0))
    assert api.post(tok, "/attendance/check-out").status_code == 200
    r = api.post(tok, "/attendance/check-in")
    assert r.status_code == 409 and "correction" in r.json()["error"]["message"]
    assert api.post(tok, "/attendance/check-out").status_code == 409


def test_a_forgotten_session_is_closed_automatically_and_flagged(api, co, clock):
    tok = co["tok"]["in9"]
    clock.set(z(2026, 2, 16, 4, 0))                         # Mon 09:30 IST
    assert api.post(tok, "/attendance/check-in").status_code == 201
    clock.set(z(2026, 2, 17, 4, 0))                         # next morning, never checked out
    fresh = api.post(tok, "/attendance/check-in")
    assert fresh.status_code == 201 and fresh.json()["work_date"] == "2026-02-17"
    first = [a for a in api.get(tok, "/attendance/mine?start=2026-02-16&end=2026-02-16").json()["items"]][0]
    assert first["auto_closed"] is True and first["check_out"].startswith("2026-02-16T12:00")      # check-in + 8 h (no shift)
    assert first["worked_hours"] == 8.0
    # forgetting again and trying to check out much later: the old session is closed, the person is told to request a correction
    clock.set(z(2026, 2, 18, 12, 0))
    r = api.post(tok, "/attendance/check-out")
    assert r.status_code == 409 and "correction" in r.json()["error"]["message"]
    second = api.get(tok, "/attendance/mine?start=2026-02-17&end=2026-02-17").json()["items"][0]
    assert second["auto_closed"] is True and api.get(tok, "/attendance/today").json()["record"] is None


def test_a_forgotten_session_never_looks_live_and_break_buttons_get_a_clear_answer(api, co, clock):
    """The page used to show 'Working' + Start break for a session nobody closed; pressing it answered 400 and silently closed the day."""
    stale_then_break, stale_then_today = co["tok"]["in5"], co["tok"]["in6"]
    clock.set(z(2026, 3, 2, 4, 0))
    for tok in (stale_then_break, stale_then_today):
        assert api.post(tok, "/attendance/check-in").status_code == 201
    clock.set(z(2026, 3, 4, 4, 0))                          # two days later, never checked out
    # reading today's state closes the forgotten session, so the page offers Check in / a correction rather than Start break
    rec = api.get(stale_then_today, "/attendance/today").json()["record"]
    assert rec is None or (rec["check_out"] is not None and rec["auto_closed"] is True)
    assert api.post(stale_then_today, "/attendance/break/start").status_code == 400                  # nothing open any more: plain message
    # pressing the button on a page that was loaded earlier: a clear conflict, not an anonymous 400
    r = api.post(stale_then_break, "/attendance/break/start")
    assert r.status_code == 409 and "correction" in r.json()["error"]["message"]
    first = api.get(stale_then_break, "/attendance/mine?start=2026-03-02&end=2026-03-02").json()["items"][0]
    assert first["auto_closed"] is True and first["check_out"] is not None
    assert api.post(stale_then_break, "/attendance/break/end").status_code == 400


def test_break_start_and_end_work_inside_a_normal_day(api, co, clock):
    tok = co["tok"]["in7"]
    clock.set(z(2026, 3, 9, 4, 0))
    assert api.post(tok, "/attendance/check-in").status_code == 201
    clock.set(z(2026, 3, 9, 6, 0))
    r = api.post(tok, "/attendance/break/start")
    assert r.status_code == 200 and r.json()["on_break"] is True
    assert api.post(tok, "/attendance/break/start").status_code == 409                               # already on a break
    clock.set(z(2026, 3, 9, 6, 30))
    ended = api.post(tok, "/attendance/break/end")
    assert ended.status_code == 200 and ended.json()["on_break"] is False and ended.json()["break_minutes"] == 30


# ---------------------------------------------------------------------------------- geo-fence

def test_geofence_blocks_office_check_in_outside_the_radius(api, co, clock):
    hr, f = co["tok"]["hr"], co["f"]
    clock.set(z(2026, 3, 2, 4, 0))
    bid = co["branch"]
    assert api.put(co["tok"]["in1"], f"/attendance/geofences/{bid}", {"required": False}).status_code == 403
    assert api.put(hr, f"/attendance/geofences/{bid}", {"required": True}).status_code == 422          # needs a centre and radius
    assert api.put(hr, f"/attendance/geofences/{bid}", {"lat": 91, "lng": 0, "radius_m": 100}).status_code == 422
    assert api.put(hr, f"/attendance/geofences/{bid}", {"lat": 22.5726, "lng": 88.3639, "radius_m": 200, "required": True}).status_code == 200
    try:
        t = co["tok"]["in1"]
        assert api.get(t, "/attendance/today").json()["geofence_required"] is True
        assert api.post(t, "/attendance/check-in").status_code == 422                                 # no location sent
        far = api.post(t, "/attendance/check-in", {"lat": 22.60, "lng": 88.40})
        assert far.status_code == 403 and "from Kolkata" in far.json()["error"]["message"]
        wfh = api.post(co["tok"]["in2"], "/attendance/check-in", {"work_mode": "wfh"})                # working from home is exempt
        assert wfh.status_code == 201
        near = api.post(t, "/attendance/check-in", {"lat": 22.5730, "lng": 88.3640})
        assert near.status_code == 201 and near.json()["work_mode"] == "office"
        assert api.get(f, "/attendance/geofences").json()["items"][0]["required"] is True
    finally:
        api.put(hr, f"/attendance/geofences/{bid}", {"required": False})


# ---------------------------------------------------------------------------------- corrections

def _ask(api, tok, cin="2026-03-09T09:00", cout="2026-03-09T18:00", reason="Forgot to check out"):
    return api.post(tok, "/attendance/corrections", {"check_in": cin, "check_out": cout, "reason": reason})


def test_correction_request_validation(api, co, clock):
    clock.set(z(2026, 3, 10, 6, 0))
    t = co["tok"]["in3"]
    assert _ask(api, t, cout="2026-03-09T08:00").status_code == 400           # out before in
    assert _ask(api, t, cin="2026-03-08T09:00", cout="2026-03-09T10:00").status_code == 400   # > 24 h
    assert _ask(api, t, cin="2026-03-11T09:00", cout="2026-03-11T18:00").status_code == 400   # future
    assert _ask(api, t, cin="2025-11-03T09:00", cout="2025-11-03T18:00").status_code == 400   # older than 60 days
    assert _ask(api, t, reason="no").status_code == 422
    ok = _ask(api, t)
    assert ok.status_code == 201 and ok.json()["status"] == "pending"
    assert ok.json()["check_in"].startswith("2026-03-09T03:30") and ok.json()["timezone"] == "Asia/Kolkata"   # 09:00 IST stored as UTC, zone returned for display
    assert _ask(api, t).status_code == 409                                    # one pending request per day
    assert api.delete(t, f"/attendance/corrections/{ok.json()['id']}").status_code == 204
    assert api.delete(t, f"/attendance/corrections/{ok.json()['id']}").status_code == 409
    assert api.get(t, "/attendance/corrections").status_code == 403           # employees have no queue
    assert [c["status"] for c in api.get(t, "/attendance/corrections/mine").json()["items"]] == ["cancelled"]


def test_approval_applies_the_times_and_is_audited(api, co, clock):
    clock.set(z(2026, 3, 10, 6, 0))
    emp, mgr = co["tok"]["in4"], co["tok"]["mgr"]
    c = _ask(api, emp).json()
    assert [x["id"] for x in api.get(mgr, "/attendance/corrections").json()["items"]] == [c["id"]]
    assert api.get(co["tok"]["mgr2"], "/attendance/corrections").json()["items"] == []        # another manager's team: nothing
    assert api.post(co["tok"]["mgr2"], f"/attendance/corrections/{c['id']}/decision", {"approve": True}).status_code == 404
    assert api.post(emp, f"/attendance/corrections/{c['id']}/decision", {"approve": True}).status_code == 403
    assert api.post(mgr, f"/attendance/corrections/{c['id']}/decision", {"approve": False}).status_code == 400   # reasons are required
    ok = api.post(mgr, f"/attendance/corrections/{c['id']}/decision", {"approve": True, "note": "ok"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["decided_by_name"]
    rec = [a for a in api.get(emp, "/attendance/mine?start=2026-03-09&end=2026-03-09").json()["items"]][0]
    assert rec["source"] == "correction" and rec["worked_hours"] == 9.0 and rec["overtime_hours"] == 1.0 and rec["status"] == "present"
    assert api.post(mgr, f"/attendance/corrections/{c['id']}/decision", {"approve": False, "note": "x"}).status_code == 409   # already decided
    actions = {a["action"] for a in api.get(co["f"], "/admin/audit-logs?page_size=100").json()["items"]}
    assert {"attendance.correction_requested", "attendance.correction_approved"} <= actions
    inbox = api.get(emp, "/notifications").json()["items"]
    assert any("correction approved" in n["title"].lower() for n in inbox)


def test_rejection_changes_nothing(api, co, clock):
    clock.set(z(2026, 3, 11, 6, 0))
    emp, hr = co["tok"]["in5"], co["tok"]["hr"]
    c = _ask(api, emp, "2026-03-10T09:00", "2026-03-10T17:00").json()
    r = api.post(hr, f"/attendance/corrections/{c['id']}/decision", {"approve": False, "note": "Badge log shows you left at noon"})
    assert r.json()["status"] == "rejected" and r.json()["decision_note"].startswith("Badge")
    assert api.get(emp, "/attendance/mine?start=2026-03-10&end=2026-03-10").json()["total"] == 0
    assert _ask(api, emp, "2026-03-10T09:00", "2026-03-10T17:00").status_code == 201        # may ask again after a decision


def test_a_correction_fixes_an_automatically_closed_day(api, co, clock):
    emp, mgr = co["tok"]["in9"], co["tok"]["mgr"]
    clock.set(z(2026, 3, 12, 6, 0))
    c = _ask(api, emp, "2026-02-16T09:30", "2026-02-16T19:00", "Worked late, forgot to check out").json()
    assert api.post(mgr, f"/attendance/corrections/{c['id']}/decision", {"approve": True}).status_code == 200
    rec = api.get(emp, "/attendance/mine?start=2026-02-16&end=2026-02-16").json()["items"][0]
    assert rec["auto_closed"] is False and rec["source"] == "correction" and rec["worked_hours"] == 9.5


def test_managers_need_the_approve_permission_and_nobody_decides_their_own(api, co, clock):
    clock.set(z(2026, 3, 13, 6, 0))
    f, mgr = co["f"], co["tok"]["mgr"]
    c = _ask(api, co["tok"]["in7"], "2026-03-12T09:00", "2026-03-12T17:00").json()
    api.patch(f, f"/managers/{co['ids']['mgr']}", {"permissions": ["reports.view"]})
    try:
        assert api.get(mgr, "/attendance/corrections").status_code == 403
        assert api.post(mgr, f"/attendance/corrections/{c['id']}/decision", {"approve": True}).status_code == 403
    finally:
        api.patch(f, f"/managers/{co['ids']['mgr']}", {"permissions": None})
    own = _ask(api, f, "2026-03-12T09:00", "2026-03-12T17:00")                    # a founder asking for themselves
    assert own.status_code == 201
    assert api.post(f, f"/attendance/corrections/{own.json()['id']}/decision", {"approve": True}).status_code == 403
    assert own.json()["id"] not in [x["id"] for x in api.get(f, "/attendance/corrections").json()["items"]]
    assert api.post(f, f"/attendance/corrections/{c['id']}/decision", {"approve": True, "note": "fine"}).status_code == 200   # founder sees all


# ----------------------------------------------------------------------------------- reporting

def test_reports_carry_the_new_measures(api, co, clock):
    mgr, hr = co["tok"]["mgr"], co["tok"]["hr"]
    s = api.get(mgr, "/attendance/summary?start=2026-01-01&end=2026-03-31").json()["items"]
    by = {r["user_id"]: r for r in s}
    r6 = by[co["ids"]["in6"]]
    assert r6["late_days"] == 1 and r6["late_minutes"] == 25 and r6["early_departures"] == 1 and r6["half_days"] == 1
    assert by[co["ids"]["in1"]]["weekend_days"] >= 1 and by[co["ids"]["in4"]]["wfh_days"] >= 1
    assert by[co["ids"]["in9"]]["auto_closed"] >= 0 and by[co["ids"]["in3"]]["holiday_days"] == 1
    rows = api.get(hr, "/attendance?start=2026-01-01&end=2026-03-31&status=holiday_work&page_size=100").json()["items"]
    assert rows and all(r["status"] == "holiday_work" for r in rows)
    csv = api.get(hr, "/reports/attendance.csv?start=2026-01-01&end=2026-03-31").text
    assert "Late minutes" in csv and "Day type" in csv and "holiday_work" in csv and "wfh" in csv
    assert api.get(co["tok"]["in1"], "/attendance/summary").status_code == 403


# ----------------------------------------------------------------------------------- isolation

def test_other_companies_cannot_see_or_decide_anything(api, co, clock):
    api.ensure_company("attco2")
    f2 = api.login("attco2", "founder@attco2.com")
    clock.set(z(2026, 3, 13, 6, 0))
    pending = _ask(api, co["tok"]["in8"], "2026-03-12T09:00", "2026-03-12T17:00").json()
    assert api.get(f2, "/attendance/corrections?status=all").json()["items"] == []
    assert api.post(f2, f"/attendance/corrections/{pending['id']}/decision", {"approve": True}).status_code == 404
    assert api.get(f2, "/attendance/shifts").json()["items"] == []
    shift = api.get(co["tok"]["hr"], "/attendance/shifts").json()["items"][0]["id"]
    assert api.post(f2, "/attendance/shift-assignments", {"shift_id": shift, "user_ids": [1]}).status_code == 404
    assert api.put(f2, f"/attendance/geofences/{co['branch']}", {"required": False}).status_code == 404
    assert api.get(f2, "/attendance?start=2026-01-01&end=2026-12-31").json()["items"] == []
