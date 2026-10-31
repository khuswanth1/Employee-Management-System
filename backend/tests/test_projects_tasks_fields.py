"""Project and task detail fields: codes, risk, visibility, task types, labels, hours, changes-requested review."""
from datetime import date, timedelta

import pytest
from app.db.base import utcnow


def msg(r):
    return r.json()["error"]["message"]


@pytest.fixture(scope="module")
def pj(api, org):
    """A project owned by a fresh manager with one assigned employee, plus an unrelated employee."""
    f = org["founder"]
    mgr = api.add_user(f, "pj.mgr@acme.com", "manager")
    emp = api.add_user(f, "pj.emp@acme.com", "employee", manager_id=mgr["id"])
    other = api.add_user(f, "pj.other@acme.com", "employee")
    mt, et, ot = (api.login("acme", f"pj.{n}@acme.com") for n in ("mgr", "emp", "other"))
    r = api.post(mt, "/projects", {"name": "Website relaunch", "code": "web-1", "category": " Marketing ", "risk_level": "high",
                                   "estimated_hours": 400, "tags": ["Q4", "q4", " launch "], "member_ids": [emp["id"]]})
    assert r.status_code == 201, r.text
    return {"mgr": mt, "emp": et, "other": ot, "emp_id": emp["id"], "project": r.json()}


# ---- projects -------------------------------------------------------------------------------------

def test_project_fields_are_normalised(pj):
    p = pj["project"]
    assert p["code"] == "WEB-1" and p["category"] == "Marketing" and p["risk_level"] == "high"
    assert p["tags"] == ["Q4", "launch"] and p["visibility"] == "restricted" and p["estimated_hours"] == 400


def test_code_is_generated_and_unique(api, pj):
    auto = api.post(pj["mgr"], "/projects", {"name": "No code given"}).json()
    assert auto["code"] == f"PRJ-{auto['id']:04d}"
    dup = api.post(pj["mgr"], "/projects", {"name": "Copycat", "code": "web-1"})
    assert dup.status_code == 409


@pytest.mark.parametrize("payload", [
    {"risk_level": "extreme"}, {"visibility": "public"}, {"code": "a b"}, {"estimated_hours": -1}, {"estimated_hours": 99999},
    {"tags": ["x" * 41]}, {"category": "c" * 61},
])
def test_invalid_project_input(api, pj, payload):
    assert api.post(pj["mgr"], "/projects", {"name": "Bad input", **payload}).status_code == 422


def test_completion_date_follows_status(api, pj):
    p = api.post(pj["mgr"], "/projects", {"name": "Finish me"}).json()
    done = api.patch(pj["mgr"], f"/projects/{p['id']}", {"status": "completed"}).json()
    assert done["completed_on"] == utcnow().date().isoformat()
    reopened = api.patch(pj["mgr"], f"/projects/{p['id']}", {"status": "active"}).json()
    assert reopened["completed_on"] is None


def test_partial_update_keeps_fields(api, pj):
    p = pj["project"]
    r = api.patch(pj["mgr"], f"/projects/{p['id']}", {"risk_level": "critical"})
    assert r.json()["risk_level"] == "critical" and r.json()["code"] == "WEB-1" and r.json()["category"] == "Marketing"


def test_restricted_project_is_hidden_from_non_members(api, pj):
    pid = pj["project"]["id"]
    assert api.get(pj["other"], f"/projects/{pid}").status_code == 404
    assert api.get(pj["emp"], f"/projects/{pid}").status_code == 200


def test_company_visibility_is_read_only(api, pj):
    pid = pj["project"]["id"]
    api.patch(pj["mgr"], f"/projects/{pid}", {"visibility": "company"})
    seen = api.get(pj["other"], f"/projects/{pid}")
    assert seen.status_code == 200 and seen.json()["can_edit"] is False
    assert api.patch(pj["other"], f"/projects/{pid}", {"name": "Hijacked"}).status_code == 403
    assert api.post(pj["other"], f"/projects/{pid}/tasks", {"title": "Sneaky task"}).status_code == 403
    api.patch(pj["mgr"], f"/projects/{pid}", {"visibility": "restricted"})
    assert api.get(pj["other"], f"/projects/{pid}").status_code == 404


def test_company_visibility_stops_at_tenant_border(api, org, pj):
    api.ensure_company("globex")
    g = api.login("globex", "founder@globex.com")
    api.patch(pj["mgr"], f"/projects/{pj['project']['id']}", {"visibility": "company"})
    assert api.get(g, f"/projects/{pj['project']['id']}").status_code == 404
    api.patch(pj["mgr"], f"/projects/{pj['project']['id']}", {"visibility": "restricted"})


def test_list_filters(api, pj):
    hits = api.get(pj["mgr"], "/projects", params={"risk_level": "critical"}).json()["items"]
    assert [p["code"] for p in hits] == ["WEB-1"]
    assert api.get(pj["mgr"], "/projects", params={"q": "web-1"}).json()["total"] == 1
    assert api.get(pj["mgr"], "/projects", params={"category": "marketing"}).json()["total"] == 1


# ---- tasks ----------------------------------------------------------------------------------------

@pytest.fixture()
def task(api, pj):
    r = api.post(pj["mgr"], f"/projects/{pj['project']['id']}/tasks", {
        "title": "Fix login redirect", "task_type": "bug", "labels": ["urgent", "Urgent", "web"], "assignee_id": pj["emp_id"],
        "estimated_hours": 6, "start_date": utcnow().date().isoformat(), "due_date": (utcnow().date() + timedelta(days=3)).isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def test_task_fields_roundtrip(task):
    assert task["task_type"] == "bug" and task["labels"] == ["urgent", "web"] and task["estimated_hours"] == 6 and task["actual_hours"] is None


@pytest.mark.parametrize("payload", [
    {"task_type": "chore"}, {"estimated_hours": -2}, {"actual_hours": 20000}, {"labels": ["y" * 41]},
    {"start_date": "2030-02-01", "due_date": "2030-01-01"},
])
def test_invalid_task_input(api, pj, payload):
    assert api.post(pj["mgr"], f"/projects/{pj['project']['id']}/tasks", {"title": "Bad task", **payload}).status_code == 422


def test_task_dates_checked_against_stored_values(api, pj, task):
    r = api.patch(pj["mgr"], f"/tasks/{task['id']}", {"due_date": (utcnow().date() - timedelta(days=5)).isoformat()})
    assert r.status_code == 400 and "start_date" in msg(r)


def test_assignee_logs_hours_but_cannot_retype_the_task(api, pj, task):
    ok = api.patch(pj["emp"], f"/tasks/{task['id']}", {"actual_hours": 2.5, "progress": 30})
    assert ok.status_code == 200 and ok.json()["actual_hours"] == 2.5
    assert api.patch(pj["emp"], f"/tasks/{task['id']}", {"task_type": "feature"}).status_code == 403
    assert api.patch(pj["emp"], f"/tasks/{task['id']}", {"estimated_hours": 1}).status_code == 403
    assert api.patch(pj["other"], f"/tasks/{task['id']}", {"actual_hours": 1}).status_code in (403, 404)


def test_project_hours_are_summed_from_tasks(api, pj, task):
    api.patch(pj["emp"], f"/tasks/{task['id']}", {"actual_hours": 4})
    p = api.get(pj["mgr"], f"/projects/{pj['project']['id']}").json()
    assert p["task_estimated_hours"] >= 6 and p["task_actual_hours"] >= 4


def test_changes_requested_needs_comment_and_goes_back_to_work(api, pj, task):
    tid = task["id"]
    assert api.patch(pj["emp"], f"/tasks/{tid}", {"status": "review"}).status_code == 200
    assert api.post(pj["mgr"], f"/tasks/{tid}/review", {"approved": False}).status_code == 422
    assert api.post(pj["mgr"], f"/tasks/{tid}/review", {"approved": False, "note": "   "}).status_code == 422
    r = api.post(pj["mgr"], f"/tasks/{tid}/review", {"approved": False, "note": "Handle the expired session case"})
    assert r.status_code == 200 and r.json()["status"] == "changes_requested" and "expired session" in r.json()["review_notes"]
    # the status cannot be set directly, and the assignee resubmits through the normal path
    assert api.patch(pj["mgr"], f"/tasks/{tid}", {"status": "changes_requested"}).status_code == 400
    assert api.patch(pj["emp"], f"/tasks/{tid}", {"status": "review"}).status_code == 200
    done = api.post(pj["mgr"], f"/tasks/{tid}/review", {"approved": True}).json()
    assert done["status"] == "done" and done["completed_on"] == utcnow().date().isoformat()


def test_changes_requested_counts_as_open_work(api, pj, task):
    tid = task["id"]
    api.patch(pj["emp"], f"/tasks/{tid}", {"status": "review"})
    api.post(pj["mgr"], f"/tasks/{tid}/review", {"approved": False, "note": "More tests"})
    d = api.get(pj["emp"], "/dashboard").json()
    assert d["my_tasks"]["changes_requested"] >= 1


def test_task_type_filter(api, pj, task):
    bugs = api.get(pj["mgr"], f"/projects/{pj['project']['id']}/tasks", params={"task_type": "bug"}).json()["items"]
    assert bugs and all(t["task_type"] == "bug" for t in bugs)
