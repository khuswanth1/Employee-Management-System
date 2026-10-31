"""Business workflows end to end through the HTTP API."""
from datetime import date, timedelta

from tests.conftest import PW
from app.db.base import utcnow


def _monday_after(d: date, weeks: int = 1) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7) + timedelta(weeks=weeks - 1)


# ---- employees ---------------------------------------------------------------------------------

def test_employee_lifecycle(api):
    api.make_company("lifecy")
    f = api.login("lifecy", "founder@lifecy.com")
    hr_user = api.add_user(f, "hr@lifecy.com", "hr")
    hr = api.login("lifecy", "hr@lifecy.com")
    dept = api.post(hr, "/departments", {"name": "Engineering"}).json()
    assert api.post(hr, "/departments", {"name": "engineering"}).status_code == 409
    mgr = api.add_user(f, "m@lifecy.com", "manager", department_id=dept["id"])  # managers are founder-controlled
    emp = api.add_user(hr, "e@lifecy.com", "employee", department_id=dept["id"], manager_id=mgr["id"])
    assert emp["status"] == "onboarding"
    assert api.post(hr, "/employees", {"email": "E@lifecy.com", "full_name": "Dup", "password": PW}).status_code == 409
    # onboarding checklist completion activates the employee
    items = api.get(hr, f"/employees/{emp['id']}/checklist").json()["items"]
    assert len(items) >= 3
    for it in items:
        assert api.patch(hr, f"/checklist/{it['id']}", {"done": True}).status_code == 200
    assert api.get(hr, f"/employees/{emp['id']}").json()["status"] == "active"
    # search + filter + pagination
    r = api.get(hr, "/employees?q=lifecy&department_id=%d&page_size=1" % dept["id"]).json()
    assert r["total"] == 2 and len(r["items"]) == 1
    assert api.delete(hr, f"/departments/{dept['id']}").status_code == 409
    # document upload/download, permission and blocked types
    up = api.c.post(f"/api/v1/employees/{emp['id']}/documents", headers=api.h(hr), files={"file": ("contract.pdf", b"%PDF-1.4 hi", "application/pdf")}, data={"doc_type": "contract"})
    assert up.status_code == 201
    assert api.c.get(f"/api/v1/documents/{up.json()['id']}/download", headers=api.h(hr)).content == b"%PDF-1.4 hi"
    emp_tok = api.login("lifecy", "e@lifecy.com")
    assert api.c.get(f"/api/v1/documents/{up.json()['id']}/download", headers=api.h(emp_tok)).status_code == 200
    other = api.add_user(hr, "o@lifecy.com")
    other_tok = api.login("lifecy", "o@lifecy.com")
    assert api.c.get(f"/api/v1/documents/{up.json()['id']}/download", headers=api.h(other_tok)).status_code == 403
    bad = api.c.post(f"/api/v1/employees/{emp['id']}/documents", headers=api.h(hr), files={"file": ("run.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    traversal = api.c.post(f"/api/v1/employees/{emp['id']}/documents", headers=api.h(hr), files={"file": ("../../etc/passwd.txt", b"x", "text/plain")})
    assert traversal.status_code == 201 and "/" not in traversal.json()["name"] and traversal.json()["name"] == "passwd.txt"
    # offboarding re-parents reports and revokes access
    assert api.post(hr, f"/employees/{mgr['id']}/offboard").status_code == 200
    assert api.get(hr, f"/employees/{emp['id']}").json()["manager_id"] is None
    assert api.post(hr, f"/employees/{mgr['id']}/offboard").status_code == 409
    audit = api.get(f, "/admin/audit-logs?action=employee.").json()
    assert audit["total"] >= 4


def test_user_limit_enforced(api):
    api.make_company("tiny")
    adm = api.admin_token()
    cid = [c for c in api.get(adm, "/platform/companies").json()["items"] if c["slug"] == "tiny"][0]["id"]
    api.patch(adm, f"/platform/companies/{cid}", {"max_users": 2})
    f = api.login("tiny", "founder@tiny.com")
    api.add_user(f, "one@tiny.com")
    r = api.post(f, "/employees", {"email": "two@tiny.com", "full_name": "Two Two", "password": PW})
    assert r.status_code == 402


# ---- projects & tasks -------------------------------------------------------------------------

def test_project_task_workflow(api, org):
    mgr, mgr2, emp, emp2, hr, f = (org[k] for k in ("mgr", "mgr2", "emp", "emp2", "hr", "founder"))
    ids = org["ids"]
    due = (utcnow().date() + timedelta(days=10)).isoformat()
    p = api.post(mgr, "/projects", {"name": "Website Revamp", "due_date": due, "member_ids": [ids["emp"]]}).json()
    assert api.post(emp, "/projects", {"name": "x"}).status_code == 403
    assert api.post(f, "/projects", {"name": "Founder project"}).status_code == 403
    assert api.post(mgr, "/projects", {"name": "Bad", "start_date": "2030-02-01", "due_date": "2030-01-01"}).status_code == 422
    # visibility
    assert api.get(emp, f"/projects/{p['id']}").status_code == 200
    assert api.get(emp2, f"/projects/{p['id']}").status_code == 404
    assert api.get(mgr2, f"/projects/{p['id']}").status_code == 404
    assert api.get(f, f"/projects/{p['id']}").status_code == 200
    assert api.patch(mgr2, f"/projects/{p['id']}", {"name": "xx"}).status_code == 404

    t1 = api.post(mgr, f"/projects/{p['id']}/tasks", {"title": "Design mockups", "assignee_id": ids["emp"], "priority": "high", "due_date": due}).json()
    t2 = api.post(mgr, f"/projects/{p['id']}/tasks", {"title": "Implement pages", "assignee_id": ids["emp"]}).json()
    assert api.get(emp2, f"/tasks/{t1['id']}").status_code == 404
    # dependency: t2 needs t1; cycles and cross-project refs are rejected
    assert api.put(mgr, f"/tasks/{t2['id']}/dependencies", {"depends_on": [t1["id"]]}).status_code == 200
    assert api.put(mgr, f"/tasks/{t1['id']}/dependencies", {"depends_on": [t2["id"]]}).status_code == 400
    assert api.put(mgr, f"/tasks/{t1['id']}/dependencies", {"depends_on": [t1["id"]]}).status_code == 400
    r = api.patch(emp, f"/tasks/{t2['id']}", {"status": "in_progress"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "blocked_by_dependency"
    # assignee limits
    assert api.patch(emp, f"/tasks/{t1['id']}", {"title": "renamed"}).status_code == 403
    assert api.patch(emp, f"/tasks/{t1['id']}", {"status": "done"}).status_code == 403
    assert api.patch(emp, f"/tasks/{t1['id']}", {"status": "in_progress", "progress": 40}).status_code == 200
    assert api.patch(emp, f"/tasks/{t1['id']}", {"progress": 101}).status_code == 422
    assert api.patch(emp2, f"/tasks/{t1['id']}", {"progress": 50}).status_code == 404
    # review loop
    assert api.post(mgr, f"/tasks/{t1['id']}/review", {"approved": True}).status_code == 400  # not in review yet
    assert api.patch(emp, f"/tasks/{t1['id']}", {"status": "review"}).status_code == 200
    assert api.post(emp, f"/tasks/{t1['id']}/review", {"approved": True}).status_code == 403
    assert api.post(mgr2, f"/tasks/{t1['id']}/review", {"approved": True}).status_code in (403, 404)
    rej = api.post(mgr, f"/tasks/{t1['id']}/review", {"approved": False, "note": "needs polish"}).json()
    assert rej["status"] == "changes_requested" and rej["review_notes"] == "needs polish"
    assert api.post(mgr, f"/tasks/{t1['id']}/review", {"approved": False}).status_code in (400, 422)  # a comment is required
    api.patch(emp, f"/tasks/{t1['id']}", {"status": "review"})
    done = api.post(mgr, f"/tasks/{t1['id']}/review", {"approved": True}).json()
    assert done["status"] == "done" and done["progress"] == 100 and done["approved_by"] == ids["mgr"]
    assert api.patch(emp, f"/tasks/{t2['id']}", {"status": "in_progress"}).status_code == 200  # unblocked
    proj = api.get(mgr, f"/projects/{p['id']}").json()
    assert proj["task_count"] == 2 and proj["done_count"] == 1 and 0 < proj["progress"] < 100
    # notifications generated for assignee and manager
    titles = [n["title"] for n in api.get(emp, "/notifications").json()["items"]]
    assert "New task assigned" in titles and "Task approved" in titles
    assert "Task ready for review" in [n["title"] for n in api.get(mgr, "/notifications").json()["items"]]
    # milestones + membership rules
    ms = api.post(mgr, f"/projects/{p['id']}/milestones", {"title": "Beta", "due_date": due}).json()
    assert api.patch(mgr, f"/milestones/{ms['id']}", {"completed": True}).json()["completed"] is True
    assert api.put(mgr, f"/projects/{p['id']}/members", {"member_ids": []}).status_code == 400  # emp has an open task
    # attachments
    up = api.c.post(f"/api/v1/tasks/{t2['id']}/attachments", headers=api.h(emp), files={"file": ("spec.txt", b"hello", "text/plain")})
    assert up.status_code == 201
    assert api.c.get(f"/api/v1/attachments/{up.json()['id']}/download", headers=api.h(emp)).content == b"hello"
    assert api.c.get(f"/api/v1/attachments/{up.json()['id']}/download", headers=api.h(emp2)).status_code == 404
    # my tasks / overdue flag
    late = api.post(mgr, f"/projects/{p['id']}/tasks", {"title": "Late", "assignee_id": ids["emp"], "due_date": (utcnow().date() - timedelta(days=2)).isoformat()}).json()
    assert late["overdue"] is True
    assert any(t["id"] == late["id"] for t in api.get(emp, "/tasks/mine").json()["items"])
    # csv export neutralises formulas
    api.post(mgr, f"/projects/{p['id']}/tasks", {"title": "=HYPERLINK(\"http://evil\")"})
    csv_text = api.get(mgr, "/reports/tasks.csv").text
    assert "'=HYPERLINK" in csv_text and ",=HYPERLINK" not in csv_text


# ---- daily updates ---------------------------------------------------------------------------

def test_daily_update_flow(api, org):
    emp, emp2, mgr, mgr2 = org["emp"], org["emp2"], org["mgr"], org["mgr2"]
    body = {"work_date": utcnow().date().isoformat(), "completed": "Built login", "hours_worked": 7.5, "blockers": "Waiting for API keys", "next_plan": "Tests"}
    u = api.post(emp, "/daily-updates", body).json()
    again = api.post(emp, "/daily-updates", {**body, "hours_worked": 8}).json()
    assert again["id"] == u["id"] and again["hours_worked"] == 8  # upsert per day
    assert api.post(emp, "/daily-updates", {**body, "work_date": (utcnow().date() + timedelta(days=1)).isoformat()}).status_code == 400
    assert api.post(emp, "/daily-updates", {**body, "work_date": (utcnow().date() - timedelta(days=30)).isoformat()}).status_code == 400
    assert api.post(emp, "/daily-updates", {**body, "hours_worked": 30}).status_code == 422
    team = api.get(mgr, "/daily-updates/team").json()
    assert any(x["id"] == u["id"] and x["has_blockers"] for x in team["items"])
    assert api.get(mgr2, "/daily-updates/team").json()["total"] == 0
    assert api.post(mgr2, f"/daily-updates/{u['id']}/review", {"status": "reviewed"}).status_code == 403
    assert api.post(emp2, f"/daily-updates/{u['id']}/review", {"status": "reviewed"}).status_code == 403
    rv = api.post(mgr, f"/daily-updates/{u['id']}/review", {"status": "needs_changes", "comment": "Add detail"}).json()
    assert rv["review_status"] == "needs_changes"
    assert "Daily update needs changes" in [n["title"] for n in api.get(emp, "/notifications").json()["items"]]
    assert api.get(emp, "/daily-updates/mine").json()["total"] >= 1
    assert api.get(emp2, "/daily-updates/mine").json()["total"] == 0


# ---- leave -----------------------------------------------------------------------------------

def test_leave_workflow(api, org):
    emp, mgr, hr, mgr2 = org["emp"], org["mgr"], org["hr"], org["mgr2"]
    types = {t["name"]: t for t in api.get(emp, "/leave/types").json()["items"]}
    annual, unpaid = types["Annual Leave"], types["Unpaid Leave"]
    start = _monday_after(utcnow().date(), 3)
    # a holiday inside the range reduces counted days
    assert api.post(hr, "/leave/holidays", {"name": "Founders Day", "date": (start + timedelta(days=1)).isoformat()}).status_code == 201
    r = api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": start.isoformat(), "end_date": (start + timedelta(days=6)).isoformat(), "reason": "Trip"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["days"] == 4  # Mon, Wed, Thu, Fri (Tue is a holiday, weekend skipped)
    # overlap and balance checks
    assert api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": start.isoformat(), "end_date": start.isoformat()}).status_code == 409
    assert api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": (start + timedelta(weeks=8)).isoformat(), "end_date": (start + timedelta(weeks=12)).isoformat()}).status_code == 400
    assert api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": "2020-01-06", "end_date": "2020-01-07"}).status_code == 400
    assert api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": "2030-01-10", "end_date": "2030-01-05"}).status_code == 422
    sat = start + timedelta(days=5)
    assert api.post(emp, "/leave/requests", {"leave_type_id": unpaid["id"], "start_date": sat.isoformat(), "end_date": (sat + timedelta(days=1)).isoformat()}).status_code == 400  # weekend only
    # approval permissions
    assert api.post(emp, f"/leave/requests/{req['id']}/decision", {"approved": True}).status_code == 403
    assert api.post(mgr2, f"/leave/requests/{req['id']}/decision", {"approved": True}).status_code == 403
    assert "Leave request" in [n["title"] for n in api.get(mgr, "/notifications").json()["items"]]
    assert api.get(mgr2, "/leave/requests").json()["total"] == 0
    bal_before = [b for b in api.get(emp, "/leave/balances").json()["items"] if b["leave_type"] == "Annual Leave"][0]
    ok = api.post(mgr, f"/leave/requests/{req['id']}/decision", {"approved": True, "note": "Enjoy"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    bal_after = [b for b in api.get(emp, "/leave/balances").json()["items"] if b["leave_type"] == "Annual Leave"][0]
    assert bal_after["remaining"] == bal_before["remaining"] - 4
    assert api.post(mgr, f"/leave/requests/{req['id']}/decision", {"approved": True}).status_code == 409  # already decided
    # cancel an approved future leave refunds the balance
    assert api.post(emp, f"/leave/requests/{req['id']}/cancel").json()["status"] == "cancelled"
    refunded = [b for b in api.get(emp, "/leave/balances").json()["items"] if b["leave_type"] == "Annual Leave"][0]
    assert refunded["remaining"] == bal_before["remaining"]
    assert api.post(emp, f"/leave/requests/{req['id']}/cancel").status_code == 409
    # reject path + cannot self-approve
    r2 = api.post(emp, "/leave/requests", {"leave_type_id": annual["id"], "start_date": start.isoformat(), "end_date": start.isoformat()}).json()
    assert api.post(hr, f"/leave/requests/{r2['id']}/decision", {"approved": False, "note": "Busy"}).json()["status"] == "rejected"
    own = api.post(mgr, "/leave/requests", {"leave_type_id": annual["id"], "start_date": start.isoformat(), "end_date": start.isoformat()}).json()
    assert api.post(mgr, f"/leave/requests/{own['id']}/decision", {"approved": True}).status_code == 403
    assert api.post(hr, f"/leave/requests/{own['id']}/decision", {"approved": True}).status_code == 200  # HR may approve a manager
    cal = api.get(hr, f"/leave/calendar?start={start}&end={start + timedelta(days=30)}").json()
    assert any(h["name"] == "Founders Day" for h in cal["holidays"]) and len(cal["leaves"]) >= 1
    # employees only see their own entries in the calendar
    assert all(l["user_id"] == org["ids"]["emp"] for l in api.get(emp, f"/leave/calendar?start={start}&end={start + timedelta(days=30)}").json()["leaves"])


def test_new_leave_type_creates_balances(api, org):
    t = api.post(org["hr"], "/leave/types", {"name": "Study Leave", "annual_quota": 5, "paid": True}).json()
    bal = [b for b in api.get(org["emp"], "/leave/balances").json()["items"] if b["leave_type_id"] == t["id"]]
    assert bal and bal[0]["allocated"] == 5


# ---- attendance ------------------------------------------------------------------------------

def test_attendance_flow(api, org):
    emp, mgr, mgr2 = org["emp2"], org["mgr"], org["mgr2"]
    assert api.post(emp, "/attendance/check-out").status_code == 400
    assert api.post(emp, "/attendance/break/start").status_code == 400
    assert api.post(emp, "/attendance/check-in").status_code == 201
    assert api.post(emp, "/attendance/check-in").status_code == 409
    assert api.post(emp, "/attendance/break/start").json()["on_break"] is True
    assert api.post(emp, "/attendance/break/start").status_code == 409
    assert api.post(emp, "/attendance/break/end").status_code == 200
    assert api.post(emp, "/attendance/break/end").status_code == 400
    out = api.post(emp, "/attendance/check-out").json()
    assert out["check_out"] and out["worked_hours"] >= 0 and len(out["breaks"]) == 1
    assert api.post(emp, "/attendance/check-out").status_code == 409
    assert api.get(emp, "/attendance/mine").json()["total"] == 1
    assert api.get(mgr, "/attendance").json()["total"] >= 1
    assert api.get(mgr2, "/attendance").json()["total"] == 0
    assert any(s["days_present"] == 1 for s in api.get(mgr, "/attendance/summary").json()["items"])
    assert "Worked hours" in api.get(org["hr"], "/reports/attendance.csv").text


def test_overtime_calculation():
    from datetime import datetime, timezone
    from app.db.tenant_models import Attendance, AttendanceBreak
    from app.modules.attendance.router import metrics
    a = Attendance(user_id=1, work_date=utcnow().date(), check_in=datetime(2026, 1, 5, 8, tzinfo=timezone.utc), check_out=datetime(2026, 1, 5, 18, 30, tzinfo=timezone.utc))
    a.breaks = [AttendanceBreak(start=datetime(2026, 1, 5, 12, tzinfo=timezone.utc), end=datetime(2026, 1, 5, 12, 30, tzinfo=timezone.utc))]
    m = metrics(a, 8)
    assert m == {"worked_hours": 10.0, "break_minutes": 30, "overtime_hours": 2.0}


# ---- dashboards ------------------------------------------------------------------------------

def test_role_specific_dashboards(api, org):
    f, hr, mgr, emp = (api.get(org[k], "/dashboard").json() for k in ("founder", "hr", "mgr", "emp"))
    assert f["role"] == "founder" and {"project_status", "workload", "headcount", "overdue_tasks", "attendance_today"} <= set(f)
    assert hr["role"] == "hr" and "by_department" in hr and "project_status" not in hr
    assert mgr["role"] == "manager" and {"projects", "awaiting_review", "team_attendance"} <= set(mgr) and "headcount" not in mgr
    assert emp["role"] == "employee" and "my_tasks" in emp and "projects" not in emp and "headcount" not in emp
    assert emp["my_overdue_tasks"] >= 1 and emp["submitted_update_today"] is True


def test_csv_exports_permissions(api, org):
    assert api.get(org["emp"], "/reports/tasks.csv").status_code == 403
    assert api.get(org["mgr"], "/reports/leave.csv").status_code == 403
    assert api.get(org["hr"], "/reports/leave.csv").headers["content-type"].startswith("text/csv")


# ---- settings ---------------------------------------------------------------------------------

def test_settings_validation(api, org):
    f = org["founder"]
    assert api.put(f, "/admin/settings/standard_work_hours", {"value": "abc"}).status_code == 400
    assert api.put(f, "/admin/settings/standard_work_hours", {"value": "99"}).status_code == 400
    assert api.put(f, "/admin/settings/nonsense", {"value": "1"}).status_code == 400
    assert api.put(f, "/admin/settings/standard_work_hours", {"value": "8"}).status_code == 200
    assert api.get(f, "/admin/audit-logs?action=settings").json()["total"] >= 1


def test_hr_and_founder_crud_holidays_on_a_fixed_five_day_week(api, org):
    base = date(2031, 3, 3)  # a Monday
    assert base.weekday() == 0
    ds = lambda n: (base + timedelta(days=n)).isoformat()
    for role in ("hr", "founder"):
        r = api.post(org[role], "/leave/holidays", {"name": f"{role} day", "date": ds(1 if role == "hr" else 2)})
        assert r.status_code == 201, r.text
    hid = [h for h in api.get(org["hr"], "/leave/holidays?year=2031").json()["items"] if h["name"] == "hr day"][0]["id"]
    # update: rename and move (to a working day), duplicates and weekends rejected
    r = api.patch(org["founder"], f"/leave/holidays/{hid}", {"name": "Renamed day", "date": ds(3)})
    assert r.status_code == 200 and r.json()["name"] == "Renamed day" and r.json()["date"] == ds(3)
    assert api.patch(org["hr"], f"/leave/holidays/{hid}", {"date": ds(2)}).status_code == 409
    assert api.patch(org["hr"], f"/leave/holidays/{hid}", {"date": ds(5)}).status_code == 400  # Saturday
    assert api.post(org["hr"], "/leave/holidays", {"name": "Sunday fest", "date": ds(6)}).status_code == 400
    assert api.patch(org["hr"], f"/leave/holidays/{hid}", {"name": "x"}).status_code == 422
    assert api.patch(org["hr"], "/leave/holidays/999999", {"name": "Nope day"}).status_code == 404
    # only HR/founder may change the calendar; everyone can read it
    for role in ("mgr", "emp"):
        assert api.post(org[role], "/leave/holidays", {"name": "Sneaky", "date": ds(8)}).status_code == 403
        assert api.patch(org[role], f"/leave/holidays/{hid}", {"name": "Hacked"}).status_code == 403
        assert api.delete(org[role], f"/leave/holidays/{hid}").status_code == 403
        assert len(api.get(org[role], "/leave/holidays?year=2031").json()["items"]) == 2
    assert api.delete(org["hr"], f"/leave/holidays/{hid}").status_code == 204
    assert [h["name"] for h in api.get(org["hr"], "/leave/holidays?year=2031").json()["items"]] == ["founder day"]
    # five-day week is fixed: Sat/Sun never count and the weekend setting no longer exists
    types = {t["name"]: t for t in api.get(org["emp"], "/leave/types").json()["items"]}
    r = api.post(org["emp"], "/leave/requests", {"leave_type_id": types["Annual Leave"]["id"], "start_date": ds(7), "end_date": ds(13)})  # Mon..Sun
    assert r.status_code == 201 and r.json()["days"] == 5
    assert api.put(org["founder"], "/admin/settings/weekend_days", {"value": "6"}).status_code == 400
    assert "weekend_days" not in [s["key"] for s in api.get(org["founder"], "/admin/settings").json()["items"]]
