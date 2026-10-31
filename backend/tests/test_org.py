"""Branches, employee management, manager permissions and branch scoping (company 'orgco')."""
import pytest

from tests.conftest import PW
from app.db.base import utcnow

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(scope="module")
def co(api):
    api.make_company("orgco")
    f = api.login("orgco", "founder@orgco.com")
    north = api.post(f, "/branches", {"name": "North Office", "code": "nrt", "city": "Oslo", "country": "NO"}).json()
    south = api.post(f, "/branches", {"name": "South Office", "code": "sth", "city": "Rome", "country": "IT"}).json()
    dept = api.post(f, "/departments", {"name": "Ops"}).json()
    users = {}
    for key, role, br in [("hr_n", "hr", north), ("hr_all", "hr", None), ("mgr_n", "manager", north), ("mgr_s", "manager", south),
                          ("emp_n", "employee", north), ("emp_n2", "employee", north), ("emp_s", "employee", south)]:
        extra = {"branch_id": br["id"]} if br else {}
        users[key] = api.add_user(f, f"{key}@orgco.com", role, department_id=dept["id"], **extra)
    # reporting lines
    api.patch(f, f"/employees/{users['emp_n']['id']}", {"manager_id": users["mgr_n"]["id"]})
    api.patch(f, f"/employees/{users['emp_n2']['id']}", {"manager_id": users["mgr_n"]["id"]})
    api.patch(f, f"/employees/{users['emp_s']['id']}", {"manager_id": users["mgr_s"]["id"]})
    tok = {k: api.login("orgco", f"{k}@orgco.com") for k in users}
    return {"f": f, "north": north, "south": south, "dept": dept, "u": users, "t": tok}


# ---- branches --------------------------------------------------------------------------------------

def test_branch_crud_is_founder_only_and_validated(api, co):
    f, t = co["f"], co["t"]
    assert co["north"]["code"] == "NRT" and co["north"]["counts"] == {"employee": 0, "manager": 0, "hr": 0}
    for role in ("hr_n", "mgr_n", "emp_n"):
        assert api.post(t[role], "/branches", {"name": "Hack", "code": "HCK"}).status_code == 403
        assert api.patch(t[role], f"/branches/{co['north']['id']}", {"city": "X"}).status_code == 403
        assert api.delete(t[role], f"/branches/{co['north']['id']}").status_code == 403
        assert api.get(t[role], "/branches").status_code == 200  # forms need the list
    assert api.post(f, "/branches", {"name": "north office", "code": "ZZ1"}).status_code == 409
    assert api.post(f, "/branches", {"name": "Another", "code": "NRT"}).status_code == 409
    assert api.post(f, "/branches", {"name": "Bad", "code": "bad code!"}).status_code == 422
    assert api.post(f, "/branches", {"name": "X", "code": "ZZ1"}).status_code == 422
    r = api.patch(f, f"/branches/{co['south']['id']}", {"city": "Milan", "address": "Via Roma 1"})
    assert r.status_code == 200 and r.json()["city"] == "Milan"
    assert api.patch(f, f"/branches/{co['south']['id']}", {"name": "North Office"}).status_code == 409
    assert api.get(f, "/branches/99999").status_code == 404
    detail = api.get(f, f"/branches/{co['north']['id']}").json()
    assert {m["id"] for m in detail["members"]} >= {co["u"]["hr_n"]["id"], co["u"]["mgr_n"]["id"], co["u"]["emp_n"]["id"]}
    assert detail["counts"] == {"employee": 2, "manager": 1, "hr": 1}
    # delete blocked while people are assigned; deactivate instead; empty branch can be deleted
    assert api.delete(f, f"/branches/{co['north']['id']}").status_code == 409
    tmp = api.post(f, "/branches", {"name": "Temp Office", "code": "TMP"}).json()
    assert api.patch(f, f"/branches/{tmp['id']}", {"is_active": False}).json()["is_active"] is False
    assert api.post(f, f"/branches/{tmp['id']}/members", {"user_ids": [co["u"]["emp_s"]["id"]]}).status_code == 400  # inactive
    assert api.delete(f, f"/branches/{tmp['id']}").status_code == 204


def test_branch_member_assignment_rules(api, co):
    f = co["f"]
    fid = api.get(f, "/auth/me").json()["id"]
    assert api.post(f, f"/branches/{co['south']['id']}/members", {"user_ids": [fid]}).status_code == 400  # founders are company-wide
    assert api.post(f, f"/branches/{co['south']['id']}/members", {"user_ids": [99999]}).status_code == 400
    extra = api.add_user(f, "mover@orgco.com", "employee")
    assert extra["branch_id"] is None and extra["employee_code"].startswith("EMP-")
    assert api.post(f, f"/branches/{co['south']['id']}/members", {"user_ids": [extra["id"]]}).status_code == 200
    moved = api.get(f, f"/employees/{extra['id']}").json()
    assert moved["branch_id"] == co["south"]["id"] and moved["location"] == "Milan"
    assert api.post(co["t"]["hr_n"], f"/branches/{co['south']['id']}/members", {"user_ids": [extra["id"]]}).status_code == 403
    assert api.delete(f, f"/branches/{co['south']['id']}/members/{extra['id']}").status_code == 204
    assert api.delete(f, f"/branches/{co['south']['id']}/members/{extra['id']}").status_code == 404
    assert api.get(f, f"/employees/{extra['id']}").json()["branch_id"] is None


# ---- employees --------------------------------------------------------------------------------------

def test_employee_fields_ids_and_branch_rules(api, co):
    f, hr_n, hr_all = co["f"], co["t"]["hr_n"], co["t"]["hr_all"]
    u = api.add_user(f, "fields@orgco.com", "employee", branch_id=co["north"]["id"], employee_code="acme-100", phone="555-1", location="Remote",
                     designation="Analyst", department_id=co["dept"]["id"], manager_id=co["u"]["mgr_n"]["id"], hire_date="2026-01-05")
    assert u["employee_code"] == "ACME-100" and u["branch_id"] == co["north"]["id"] and u["location"] == "Remote"
    assert u["designation"] == "Analyst" and u["phone"] == "555-1" and u["hire_date"] == "2026-01-05"
    r = api.post(f, "/employees", {"email": "dupcode@orgco.com", "full_name": "Dup Code", "password": PW, "employee_code": "acme-100"})
    assert r.status_code == 409
    assert api.post(f, "/employees", {"email": "badcode@orgco.com", "full_name": "Bad Code", "password": PW, "employee_code": "a b"}).status_code == 422
    # reporting manager must be in the same branch
    r = api.post(f, "/employees", {"email": "cross@orgco.com", "full_name": "Cross Branch", "password": PW,
                                   "branch_id": co["south"]["id"], "manager_id": co["u"]["mgr_n"]["id"]})
    assert r.status_code == 400
    # only founders choose branches; branch HR hires into their own branch automatically
    assert api.post(hr_n, "/employees", {"email": "sneak@orgco.com", "full_name": "Sneak", "password": PW, "branch_id": co["south"]["id"]}).status_code == 403
    mine = api.post(hr_n, "/employees", {"email": "hired@orgco.com", "full_name": "Hired North", "password": PW}).json()
    assert mine["branch_id"] == co["north"]["id"]
    assert api.patch(hr_n, f"/employees/{mine['id']}", {"branch_id": co["south"]["id"]}).status_code == 403
    assert api.patch(f, f"/employees/{mine['id']}", {"branch_id": co["south"]["id"]}).json()["branch_id"] == co["south"]["id"]
    assert api.patch(f, f"/employees/{mine['id']}", {"branch_id": 99999}).status_code == 400
    # only founders create/promote managers, HR
    for role in ("manager", "hr"):
        assert api.post(hr_all, "/employees", {"email": f"{role}x@orgco.com", "full_name": "Role X", "password": PW, "role": role}).status_code == 403
    assert api.patch(hr_all, f"/employees/{u['id']}", {"role": "manager"}).status_code == 403
    assert api.patch(f, f"/employees/{u['id']}", {"employee_code": "acme-101", "phone": "555-2"}).json()["employee_code"] == "ACME-101"
    assert api.patch(f, f"/employees/{u['id']}", {"employee_code": co["u"]["emp_n"]["employee_code"]}).status_code == 409


def test_branch_hr_is_confined_to_their_branch(api, co):
    t, ids = co["t"], {k: v["id"] for k, v in co["u"].items()}
    hr_n, hr_all = t["hr_n"], t["hr_all"]
    listing = api.get(hr_n, "/employees?page_size=100").json()["items"]
    assert listing and all(e["branch_id"] == co["north"]["id"] for e in listing)
    assert ids["emp_s"] not in [e["id"] for e in listing]
    assert api.get(hr_n, f"/employees/{ids['emp_s']}").status_code == 403 or api.get(hr_n, f"/employees/{ids['emp_s']}").status_code == 404
    for call in (lambda: api.patch(hr_n, f"/employees/{ids['emp_s']}", {"designation": "x"}),
                 lambda: api.post(hr_n, f"/employees/{ids['emp_s']}/reset-password", {"new_password": "Another-Pw1"}),
                 lambda: api.post(hr_n, f"/employees/{ids['emp_s']}/offboard"),
                 lambda: api.delete(hr_n, f"/employees/{ids['emp_s']}"),
                 lambda: api.c.post(f"/api/v1/employees/{ids['emp_s']}/avatar", headers=api.h(hr_n), files={"file": ("a.png", _PNG, "image/png")})):
        assert call().status_code == 404
    assert api.patch(hr_n, f"/employees/{ids['emp_n2']}", {"designation": "Clerk"}).status_code == 200
    # company-wide HR sees both branches
    ids_all = [e["id"] for e in api.get(hr_all, "/employees?page_size=100").json()["items"]]
    assert ids["emp_s"] in ids_all and ids["emp_n"] in ids_all
    assert api.get(hr_all, f"/employees?branch_id={co['south']['id']}&page_size=100").json()["total"] >= 2
    # HR can never touch founders or board members
    fid = api.get(co["f"], "/auth/me").json()["id"]
    assert api.get(hr_all, f"/employees/{fid}").status_code in (403, 404)
    assert api.patch(hr_all, f"/employees/{fid}", {"designation": "x"}).status_code == 403
    assert fid not in [e["id"] for e in api.get(hr_all, "/employees?page_size=100").json()["items"]]
    # dashboard numbers are branch scoped for branch HR
    assert api.get(hr_n, "/dashboard").json()["headcount"] < api.get(hr_all, "/dashboard").json()["headcount"]


def test_employee_delete_rules_and_photo_management(api, co):
    f, hr_n = co["f"], co["t"]["hr_n"]
    fresh = api.add_user(f, "gone@orgco.com", "employee", branch_id=co["north"]["id"])
    # HR uploads a photo for an employee in scope; invalid files rejected; removal works; all audited
    up = api.c.post(f"/api/v1/employees/{fresh['id']}/avatar", headers=api.h(hr_n), files={"file": ("p.png", _PNG, "image/png")})
    assert up.status_code == 200
    img = api.c.get(f"/api/v1/users/{fresh['id']}/avatar", headers=api.h(hr_n))
    assert img.status_code == 200 and img.content == _PNG
    assert api.c.post(f"/api/v1/employees/{fresh['id']}/avatar", headers=api.h(hr_n), files={"file": ("p.png", b"<html>", "image/png")}).status_code == 400
    assert api.c.delete(f"/api/v1/employees/{fresh['id']}/avatar", headers=api.h(hr_n)).status_code == 204
    assert api.c.get(f"/api/v1/users/{fresh['id']}/avatar", headers=api.h(hr_n)).status_code == 404
    api.c.post(f"/api/v1/employees/{fresh['id']}/avatar", headers=api.h(hr_n), files={"file": ("p.png", _PNG, "image/png")})
    actions = [a["action"] for a in api.get(f, "/admin/audit-logs?action=employee.photo&page_size=50").json()["items"]]
    assert "employee.photo_uploaded" in actions and "employee.photo_removed" in actions
    # deletes: own account / employees with history refused; clean accounts deleted (files too)
    me_hr = api.get(hr_n, "/auth/me").json()["id"]
    assert api.delete(hr_n, f"/employees/{me_hr}").status_code == 400
    assert api.delete(co["t"]["mgr_n"], f"/employees/{fresh['id']}").status_code == 403
    assert api.delete(hr_n, f"/employees/{fresh['id']}").status_code == 204
    assert api.get(f, f"/employees/{fresh['id']}").status_code == 404
    assert api.delete(hr_n, f"/employees/{fresh['id']}").status_code == 404
    busy = co["u"]["emp_n"]
    api.post(co["t"]["emp_n"], "/attendance/check-in")
    api.post(co["t"]["emp_n"], "/daily-updates", {"work_date": utcnow().date().isoformat(), "completed": "work", "hours_worked": 1})
    r = api.delete(hr_n, f"/employees/{busy['id']}")
    assert r.status_code == 409 and "Offboard" in r.json()["error"]["message"]
    assert api.get(f, f"/employees/{busy['id']}").status_code == 200
    fid = api.get(f, "/auth/me").json()["id"]
    assert api.delete(f, f"/employees/{fid}").status_code == 400
    actions = [a["action"] for a in api.get(f, "/admin/audit-logs?action=employee.deleted").json()["items"]]
    assert actions == ["employee.deleted"]


# ---- managers: permissions, team, branch scope ------------------------------------------------------

def test_founder_configures_managers_and_permissions_are_enforced(api, co):
    f, t, ids = co["f"], co["t"], {k: v["id"] for k, v in co["u"].items()}
    mgr = t["mgr_n"]
    assert api.get(t["hr_all"], "/managers").status_code == 403
    listing = {m["id"]: m for m in api.get(f, "/managers").json()["items"]}
    assert listing[ids["mgr_n"]]["team_size"] >= 2 and "projects.manage" in listing[ids["mgr_n"]]["permissions"]
    assert {c["key"] for c in api.get(f, "/managers/permissions-catalog").json()["items"]} >= {"projects.manage", "leave.approve"}
    # by default a manager can run projects; unknown permissions and non-managers are rejected
    proj = api.post(mgr, "/projects", {"name": "Branch Portal"})
    assert proj.status_code == 201
    assert api.patch(f, f"/managers/{ids['mgr_n']}", {"permissions": ["fly.planes"]}).status_code == 400
    assert api.patch(f, f"/managers/{ids['emp_n']}", {"branch_id": co["north"]["id"]}).status_code == 404
    assert api.patch(t["hr_n"], f"/managers/{ids['mgr_n']}", {"permissions": []}).status_code == 403
    # remove permissions one by one: each endpoint family is enforced server-side
    r = api.patch(f, f"/managers/{ids['mgr_n']}", {"permissions": ["leave.approve"]})
    assert r.status_code == 200 and r.json()["permissions"] == ["leave.approve"]
    assert api.post(mgr, "/projects", {"name": "Denied"}).status_code == 403
    assert api.get(mgr, "/attendance").status_code == 403
    assert api.get(mgr, "/daily-updates/team").status_code == 403
    assert api.get(mgr, "/leave/requests").status_code == 200
    api.patch(f, f"/managers/{ids['mgr_n']}", {"permissions": ["reports.view"]})
    assert api.get(mgr, "/attendance").status_code == 200 and api.get(mgr, "/leave/requests").status_code == 403
    assert api.c.get("/api/v1/reports/tasks.csv", headers=api.h(mgr)).status_code == 200
    # restore defaults (None) and check the audit trail
    assert api.patch(f, f"/managers/{ids['mgr_n']}", {"permissions": None}).json()["permissions"] == sorted(
        {"projects.manage", "leave.approve", "updates.review", "reports.view", "attendance.approve", "employees.manage", "teams.manage"}, key=lambda k: ["projects.manage", "leave.approve", "updates.review", "reports.view", "attendance.approve", "employees.manage", "teams.manage"].index(k))
    assert api.post(mgr, "/projects", {"name": "Allowed again"}).status_code == 201
    acts = [a for a in api.get(f, "/admin/audit-logs?action=manager.updated&page_size=50").json()["items"]]
    assert acts and any(a["detail"].get("permissions") == ["leave.approve"] for a in acts)


def test_manager_team_assignment_and_branch_boundaries(api, co):
    f, t, ids = co["f"], co["t"], {k: v["id"] for k, v in co["u"].items()}
    mgr_n, mgr_s = t["mgr_n"], t["mgr_s"]
    # a branch manager cannot involve people of another branch in projects or tasks
    p = api.post(mgr_n, "/projects", {"name": "North only", "member_ids": [ids["emp_n"]]}).json()
    assert api.post(mgr_n, "/projects", {"name": "Leaky", "member_ids": [ids["emp_s"]]}).status_code == 400
    assert api.put(mgr_n, f"/projects/{p['id']}/members", {"member_ids": [ids["emp_n"], ids["emp_s"]]}).status_code == 400
    # nor see another branch's data
    assert api.get(mgr_n, f"/projects/{p['id']}").status_code == 200
    assert api.get(mgr_s, f"/projects/{p['id']}").status_code == 404
    api.post(t["emp_s"], "/attendance/check-in")
    team_ids = {a["user_id"] for a in api.get(mgr_n, "/attendance?page_size=100").json()["items"]}
    assert ids["emp_s"] not in team_ids
    # leave: a manager only decides for direct reports of their branch
    lt = api.get(t["emp_s"], "/leave/types").json()["items"][0]
    from datetime import date, timedelta
    d = utcnow().date() + timedelta(days=60)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    lr = api.post(t["emp_s"], "/leave/requests", {"leave_type_id": lt["id"], "start_date": d.isoformat(), "end_date": d.isoformat()}).json()
    assert api.post(mgr_n, f"/leave/requests/{lr['id']}/decision", {"approved": True}).status_code == 403
    assert api.post(t["hr_n"], f"/leave/requests/{lr['id']}/decision", {"approved": True}).status_code == 403  # other branch
    assert lr["id"] not in [r["id"] for r in api.get(t["hr_n"], "/leave/requests?page_size=100").json()["items"]]
    assert api.post(t["hr_all"], f"/leave/requests/{lr['id']}/decision", {"approved": True}).status_code == 200
    # founder (re)builds a team: replaces direct reports, rejects other branches / non-employees
    r = api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"]]})
    assert r.status_code == 200 and r.json()["team_size"] == 1
    assert api.get(f, f"/employees/{ids['emp_n2']}").json()["manager_id"] is None
    assert api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"], ids["emp_s"]]}).status_code == 400
    assert api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["hr_n"]]}).status_code == 400
    assert api.put(t["hr_all"], f"/managers/{ids['mgr_n']}/team", {"user_ids": []}).status_code == 403
    assert api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"], ids["emp_n2"]]}).json()["team_size"] == 2
    # reporting line + branch/department of a manager; cycles are rejected
    r = api.patch(f, f"/managers/{ids['mgr_n']}", {"reports_to": ids["hr_all"], "department_id": co["dept"]["id"]})
    assert r.status_code == 200 and r.json()["reports_to"] == ids["hr_all"]
    boss = api.add_user(f, "mgr_n2@orgco.com", "manager", branch_id=co["north"]["id"])
    assert api.patch(f, f"/managers/{boss['id']}", {"reports_to": ids["mgr_n"]}).status_code == 200
    assert api.patch(f, f"/managers/{ids['mgr_n']}", {"reports_to": boss["id"]}).status_code == 400  # cycle
    assert api.patch(f, f"/managers/{ids['mgr_n']}", {"branch_id": 99999}).status_code == 404
    api.patch(f, f"/managers/{ids['mgr_n']}", {"reports_to": None})


def test_branch_moves_release_reporting_lines_that_would_cross_branches(api, co):
    f, ids = co["f"], {k: v["id"] for k, v in co["u"].items()}
    api.put(f, f"/managers/{ids['mgr_s']}/team", {"user_ids": [ids["emp_s"]]})
    assert api.get(f, f"/employees/{ids['emp_s']}").json()["manager_id"] == ids["mgr_s"]
    # moving the employee to another branch frees them from the old branch's manager
    assert api.post(f, f"/branches/{co['north']['id']}/members", {"user_ids": [ids["emp_s"]]}).status_code == 200
    moved = api.get(f, f"/employees/{ids['emp_s']}").json()
    assert moved["branch_id"] == co["north"]["id"] and moved["manager_id"] is None
    # PATCH refuses a manager from another branch outright (explicit, nothing silently changes)
    assert api.patch(f, f"/employees/{ids['emp_s']}", {"manager_id": ids["mgr_s"]}).status_code == 400
    # a manager moved to another branch releases direct reports left behind
    api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"], ids["emp_n2"]]})
    api.patch(f, f"/managers/{ids['mgr_n']}", {"branch_id": co["south"]["id"]})
    assert api.get(f, f"/managers/{ids['mgr_n']}").status_code in (404, 405)  # no detail route; listing is the source
    mine = {m["id"]: m for m in api.get(f, "/managers").json()["items"]}
    assert mine[ids["mgr_n"]]["team_size"] == 0 and mine[ids["mgr_n"]]["branch_id"] == co["south"]["id"]
    acts = api.get(f, "/admin/audit-logs?action=branch.members_assigned&page_size=5").json()["items"]
    assert acts and acts[0]["detail"]["released_reporting_lines"]
    # restore the original layout for later tests
    api.patch(f, f"/managers/{ids['mgr_n']}", {"branch_id": co["north"]["id"]})
    api.post(f, f"/branches/{co['south']['id']}/members", {"user_ids": [ids["emp_s"]]})
    api.put(f, f"/managers/{ids['mgr_s']}/team", {"user_ids": [ids["emp_s"]]})
    api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"], ids["emp_n2"]]})


def test_branch_hr_project_and_audit_scope(api, co):
    t, ids = co["t"], {k: v["id"] for k, v in co["u"].items()}
    south = api.post(t["mgr_s"], "/projects", {"name": "South Only Programme"}).json()
    north = api.post(t["mgr_n"], "/projects", {"name": "North Only Programme"}).json()
    seen_n = {p["id"] for p in api.get(t["hr_n"], "/projects?page_size=100").json()["items"]}
    seen_all = {p["id"] for p in api.get(t["hr_all"], "/projects?page_size=100").json()["items"]}
    assert north["id"] in seen_n and south["id"] not in seen_n
    assert {north["id"], south["id"]} <= seen_all
    assert api.get(t["hr_n"], f"/projects/{south['id']}").status_code == 404
    # audit log: branch HR only sees events caused by people of their branch; company-wide HR sees everything
    north_people = {ids[k] for k in ("hr_n", "mgr_n", "emp_n", "emp_n2")}
    fid = api.get(co["f"], "/auth/me").json()["id"]
    mine = api.get(t["hr_n"], "/admin/audit-logs?page_size=100").json()["items"]
    assert mine and all(a["actor_id"] in north_people or a["actor_id"] not in (fid, ids["mgr_s"], ids["hr_all"]) for a in mine)
    assert fid not in {a["actor_id"] for a in mine}
    everything = {a["actor_id"] for a in api.get(t["hr_all"], "/admin/audit-logs?page_size=100").json()["items"]}
    assert fid in everything
    # team reports follow the same boundary
    api.post(t["emp_s"], "/attendance/check-in")
    assert ids["emp_s"] not in {a["user_id"] for a in api.get(t["hr_n"], "/attendance?page_size=100").json()["items"]}
    assert ids["emp_s"] in {a["user_id"] for a in api.get(t["hr_all"], "/attendance?page_size=100").json()["items"]}
    csv_n = api.c.get("/api/v1/reports/tasks.csv", headers=api.h(t["hr_n"])).text
    assert "South Only Programme" not in csv_n


# ---- board members ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def board(api, co):
    f = co["f"]
    r = api.post(f, "/board/members", {"email": "board1@orgco.com", "full_name": "Beatrice Board", "password": PW, "designation": "Chair",
                                        "responsibilities": "Strategy oversight", "term_start": "2026-01-01", "permissions": ["analytics.view"]})
    assert r.status_code == 201, r.text
    api.post(f, "/board/members", {"email": "board2@orgco.com", "full_name": "Bruno Board", "password": PW})
    return {"m": r.json(), "t": api.login("orgco", "board1@orgco.com"), "t2": api.login("orgco", "board2@orgco.com")}


def test_founder_manages_board_member_profiles(api, co, board):
    f, m = co["f"], board["m"]
    assert m["permissions"] == ["analytics.view"] and m["employee_code"].startswith("BRD-") and m["designation"] == "Chair"
    for role in ("hr_all", "mgr_n", "emp_n"):
        assert api.get(co["t"][role], "/board/members").status_code == 403
        assert api.post(co["t"][role], "/board/members", {"email": "x@orgco.com", "full_name": "Xx Xx", "password": PW}).status_code == 403
    assert api.post(f, "/board/members", {"email": "BOARD1@orgco.com", "full_name": "Dup", "password": PW}).status_code == 409
    assert api.post(f, "/board/members", {"email": "bad@orgco.com", "full_name": "Bad Perm", "password": PW, "permissions": ["x"]}).status_code == 422
    assert api.post(f, "/employees", {"email": "sneaky@orgco.com", "full_name": "Sneaky", "password": PW, "role": "board_member"}).status_code == 422
    got = api.get(f, f"/board/members/{m['id']}").json()
    assert got["responsibilities"] == "Strategy oversight" and got["term_start"] == "2026-01-01"
    r = api.patch(f, f"/board/members/{m['id']}", {"designation": "Vice Chair", "responsibilities": "Audit committee", "permissions": ["analytics.view", "reports.view"]})
    assert r.status_code == 200 and r.json()["designation"] == "Vice Chair" and r.json()["permissions"] == ["analytics.view", "reports.view"]
    assert api.patch(f, f"/board/members/{m['id']}", {"permissions": ["nope"]}).status_code == 422
    assert api.get(f, "/board/members/99999").status_code == 404
    assert api.get(f, f"/board/members/{co['u']['emp_n']['id']}").status_code == 404  # not a board member
    names = [x["full_name"] for x in api.get(f, "/board/members").json()["items"]]
    assert names == ["Beatrice Board", "Bruno Board"]
    # a board member sees fellow members (no contact details), HR cannot modify them
    peer = api.get(board["t"], "/board/members").json()["items"]
    assert len(peer) == 2 and "email" not in peer[0]
    assert api.patch(co["t"]["hr_all"], f"/employees/{m['id']}", {"designation": "x"}).status_code == 403
    # deactivate / reactivate / delete
    assert api.patch(f, f"/board/members/{board['m']['id']}", {"is_active": False}).json()["is_active"] is False
    assert api.c.post("/api/v1/auth/login", json={"email": "board1@orgco.com", "password": PW}).status_code == 401
    assert api.patch(f, f"/board/members/{board['m']['id']}", {"is_active": True}).json()["is_active"] is True
    tmp = api.post(f, "/board/members", {"email": "tmp@orgco.com", "full_name": "Temp Board", "password": PW}).json()
    assert api.delete(f, f"/board/members/{tmp['id']}").status_code == 204
    assert api.get(f, f"/board/members/{tmp['id']}").status_code == 404
    acts = {a["action"] for a in api.get(f, "/admin/audit-logs?action=board.&page_size=50").json()["items"]}
    assert {"board.member_created", "board.member_updated", "board.member_deleted"} <= acts


def test_board_members_get_aggregates_only_and_no_employee_data(api, co, board):
    bt, ids = board["t"], {k: v["id"] for k, v in co["u"].items()}
    data = api.get(bt, "/board/analytics")
    assert data.status_code == 200
    a = data.json()
    assert a["headcount"] >= 6 and sum(x["count"] for x in a["by_branch"]) == a["headcount"] and "board_member" not in a["by_role"]
    assert a["financial"]["available"] is False
    flat = str(a)
    assert "@orgco.com" not in flat and "Emp" not in flat  # no names or emails anywhere
    # permission-gated report: board1 only has analytics.view (updated earlier to include reports.view for the first test run)
    api.patch(co["f"], f"/board/members/{board['m']['id']}", {"permissions": ["analytics.view"]})
    assert api.c.get("/api/v1/board/reports/headcount.csv", headers=api.h(bt)).status_code == 403
    csv = api.c.get("/api/v1/board/reports/headcount.csv", headers=api.h(board["t2"]))
    assert csv.status_code == 200 and csv.text.startswith("Branch,Department,Headcount") and "@" not in csv.text
    api.patch(co["f"], f"/board/members/{board['m']['id']}", {"permissions": ["reports.view"]})
    assert api.get(bt, "/board/analytics").status_code == 403
    api.patch(co["f"], f"/board/members/{board['m']['id']}", {"permissions": ["analytics.view", "reports.view"]})
    # nothing about individual people is reachable
    for path in ("/employees", "/employees/directory", f"/employees/{ids['emp_n']}", f"/employees/{ids['emp_n']}/documents", "/branches",
                 f"/branches/{co['north']['id']}", "/managers", "/attendance", "/daily-updates/team", "/leave/requests", "/projects",
                 "/employees/my-team", "/admin/audit-logs", "/admin/usage", "/webhooks", "/reports/attendance.csv"):
        assert api.get(bt, path).status_code in (403, 404) or (path == "/projects" and api.get(bt, path).json()["total"] == 0), path
    api.post(co["t"]["emp_n"], "/auth/me/avatar", None) if False else None
    assert api.c.post("/api/v1/auth/me/avatar", headers=api.h(co["t"]["emp_n"]), files={"file": ("a.png", _PNG, "image/png")}).status_code == 200
    assert api.c.get(f"/api/v1/users/{ids['emp_n']}/avatar", headers=api.h(bt)).status_code == 404
    assert api.get(bt, "/leave/calendar?start=2026-01-01&end=2026-12-31").json()["leaves"] == []
    me = api.get(bt, "/auth/me").json()
    assert me["role"] == "board_member"
    # other roles cannot read the board analytics
    for role in ("hr_all", "mgr_n", "emp_n"):
        assert api.get(co["t"][role], "/board/analytics").status_code == 403
    assert api.get(co["f"], "/board/analytics").status_code == 200


# ---- communication hierarchy -----------------------------------------------------------------------------

def test_chat_follows_the_communication_hierarchy(api, co, board):
    f, t, ids = co["f"], co["t"], {k: v["id"] for k, v in co["u"].items()}
    fid = api.get(f, "/auth/me").json()["id"]
    dm = lambda who, other: api.post(who, "/chat/conversations", {"user_id": other})
    # employee -> founder is blocked both ways, and the directory does not even list the founder
    r = dm(t["emp_n"], fid)
    assert r.status_code == 403 and "escalation" in r.json()["error"]["message"].lower()
    assert dm(f, ids["emp_n"]).status_code == 403
    assert fid not in [u["id"] for u in api.get(t["emp_n"], "/chat/users").json()["items"]]
    # allowed: employee <-> own-branch manager / HR / peer; founder <-> manager / HR / board
    assert dm(t["emp_n"], ids["mgr_n"]).status_code == 201
    assert dm(t["emp_n"], ids["hr_n"]).status_code == 201
    assert dm(t["emp_n"], ids["emp_n2"]).status_code == 201
    assert dm(f, ids["mgr_n"]).status_code == 201 and dm(f, ids["hr_all"]).status_code == 201 and dm(f, board["m"]["id"]).status_code == 201
    # branch boundary: employees do not reach other branches' managers or peers; company-wide HR is reachable
    assert dm(t["emp_n"], ids["mgr_s"]).status_code == 403
    assert dm(t["emp_n"], ids["emp_s"]).status_code == 403
    assert dm(t["emp_n"], ids["hr_all"]).status_code == 201
    # board members talk to the founder and to each other only
    for other in (ids["mgr_n"], ids["hr_all"], ids["emp_n"]):
        assert dm(board["t"], other).status_code == 403
    assert dm(t["hr_all"], board["m"]["id"]).status_code == 403
    assert dm(board["t"], fid).status_code == 201
    assert {u["id"] for u in api.get(board["t"], "/chat/users").json()["items"]} == {fid, api.get(board["t2"], "/auth/me").json()["id"]}
    # groups: every pair must be allowed
    assert api.post(t["mgr_n"], "/chat/conversations", {"name": "Mixed", "member_ids": [ids["emp_n"], fid]}).status_code == 403
    assert api.post(t["mgr_n"], "/chat/conversations", {"name": "North team", "member_ids": [ids["emp_n"], ids["emp_n2"], ids["hr_n"]]}).status_code == 201
    conv = dm(f, ids["mgr_n"]).json()
    assert api.post(f, f"/chat/conversations/{conv['id']}/messages", {"body": "hello manager"}).status_code == 201
    assert conv["can_send"] is True


def test_founder_exceptions_allow_direct_employee_founder_chat(api, co):
    f, t, ids = co["f"], co["t"], {k: v["id"] for k, v in co["u"].items()}
    fid = api.get(f, "/auth/me").json()["id"]
    assert api.put(t["hr_all"], f"/chat/exceptions/{ids['emp_n2']}").status_code == 403
    assert api.put(f, f"/chat/exceptions/{ids['mgr_n']}").status_code == 400  # employees only
    assert api.put(f, f"/chat/exceptions/{ids['emp_n2']}").status_code == 204
    assert [u["id"] for u in api.get(f, "/chat/exceptions").json()["items"]] == [ids["emp_n2"]]
    r = api.post(t["emp_n2"], "/chat/conversations", {"user_id": fid})
    assert r.status_code == 201 and r.json()["can_send"] is True
    conv = r.json()["id"]
    assert api.post(t["emp_n2"], f"/chat/conversations/{conv}/messages", {"body": "Hi founder"}).status_code == 201
    assert api.post(f, f"/chat/conversations/{conv}/messages", {"body": "Hi back"}).status_code == 201
    assert fid in [u["id"] for u in api.get(t["emp_n2"], "/chat/users").json()["items"]]
    # other employees stay blocked, and revoking closes the line (history stays readable)
    assert api.post(t["emp_n"], "/chat/conversations", {"user_id": fid}).status_code == 403
    assert api.delete(f, f"/chat/exceptions/{ids['emp_n2']}").status_code == 204
    assert api.delete(f, f"/chat/exceptions/{ids['emp_n2']}").status_code == 404
    assert api.post(t["emp_n2"], f"/chat/conversations/{conv}/messages", {"body": "still there?"}).status_code == 403
    mine = [c for c in api.get(t["emp_n2"], "/chat/conversations").json()["items"] if c["id"] == conv][0]
    assert mine["can_send"] is False
    assert len(api.get(t["emp_n2"], f"/chat/conversations/{conv}/messages").json()["items"]) == 2
    acts = {a["action"] for a in api.get(f, "/admin/audit-logs?action=chat.exception&page_size=20").json()["items"]}
    assert acts == {"chat.exception_added", "chat.exception_removed"}


def test_escalation_workflow_employee_to_manager_hr_to_founder(api, co):
    f, t, ids = co["f"], co["t"], {k: v["id"] for k, v in co["u"].items()}
    emp, mgr = t["emp_n"], t["mgr_n"]
    api.put(f, f"/managers/{ids['mgr_n']}/team", {"user_ids": [ids["emp_n"], ids["emp_n2"]]})
    assert api.post(f, "/escalations", {"subject": "xyz", "body": "abc def", "route": "hr"}).status_code == 403  # founders do not escalate to themselves
    assert api.post(emp, "/escalations", {"subject": "ab", "body": "short"}).status_code == 422
    # employee -> manager
    e = api.post(emp, "/escalations", {"subject": "Workload too high", "body": "I am carrying three projects alone.", "route": "manager"})
    assert e.status_code == 201, e.text
    e = e.json()
    assert e["level"] == "manager" and e["assignee_id"] == ids["mgr_n"] and e["status"] == "open" and e["can_act"] is False
    # only the line manager sees it
    assert api.get(mgr, f"/escalations/{e['id']}").status_code == 200
    for who in ("mgr_s", "emp_n2", "emp_s", "hr_n"):
        assert api.get(t[who], f"/escalations/{e['id']}").status_code == 404, who
    assert api.get(f, "/escalations?box=inbox").json()["total"] == 0
    assert [x["id"] for x in api.get(mgr, "/escalations?box=inbox").json()["items"]] == [e["id"]]
    assert "New escalation" in [n["title"] for n in api.get(mgr, "/notifications").json()["items"]]
    # the employee cannot act on it; the manager escalates to the founder with a note
    assert api.post(emp, f"/escalations/{e['id']}/resolve", {"resolution": "self resolve"}).status_code == 403
    assert api.post(emp, f"/escalations/{e['id']}/escalate", {"note": "please"}).status_code == 403
    assert api.post(t["mgr_s"], f"/escalations/{e['id']}/escalate", {"note": "intrude"}).status_code == 404
    up = api.post(mgr, f"/escalations/{e['id']}/escalate", {"note": "Needs headcount approval"})
    assert up.status_code == 200 and up.json()["level"] == "founder" and up.json()["status"] == "escalated"
    assert api.post(mgr, f"/escalations/{e['id']}/resolve", {"resolution": "no longer mine"}).status_code == 403
    inbox = api.get(f, "/escalations?box=inbox").json()
    assert [x["id"] for x in inbox["items"]] == [e["id"]] and inbox["items"][0]["can_act"] is True and inbox["items"][0]["escalated_by_name"]
    assert api.get(t["hr_all"], f"/escalations/{e['id']}").status_code == 404
    done = api.post(f, f"/escalations/{e['id']}/resolve", {"resolution": "Approved a new hire for Q1."})
    assert done.status_code == 200 and done.json()["status"] == "resolved" and done.json()["resolved_by_name"]
    assert api.post(f, f"/escalations/{e['id']}/resolve", {"resolution": "again"}).status_code == 403
    mine = api.get(emp, "/escalations?box=mine").json()["items"]
    assert mine[0]["status"] == "resolved" and mine[0]["resolution"].startswith("Approved")
    assert "Escalation resolved" in [n["title"] for n in api.get(emp, "/notifications").json()["items"]]
    # employee -> HR (branch scoped): HR of the same branch handles it, another branch's HR cannot see it
    h = api.post(emp, "/escalations", {"subject": "Payroll question", "body": "My allowance is missing.", "route": "hr"}).json()
    assert api.get(t["hr_n"], f"/escalations/{h['id']}").status_code == 200
    assert api.get(t["hr_all"], f"/escalations/{h['id']}").status_code == 200
    api.add_user(f, "hr_s@orgco.com", "hr", branch_id=co["south"]["id"])
    assert api.get(api.login("orgco", "hr_s@orgco.com"), f"/escalations/{h['id']}").status_code == 404
    assert api.post(t["hr_n"], f"/escalations/{h['id']}/resolve", {"resolution": "Fixed in next payroll."}).json()["status"] == "resolved"
    # managers escalate to HR only; no line manager -> clear error
    assert api.post(mgr, "/escalations", {"subject": "Budget issue", "body": "Need support.", "route": "manager"}).status_code == 400
    assert api.post(mgr, "/escalations", {"subject": "Budget issue", "body": "Need support.", "route": "hr"}).status_code == 201
    api.patch(f, f"/employees/{ids['emp_n2']}", {"manager_id": None})
    r = api.post(t["emp_n2"], "/escalations", {"subject": "No boss", "body": "Who handles this?", "route": "manager"})
    assert r.status_code == 400 and "HR" in r.json()["error"]["message"]
    acts = {a["action"] for a in api.get(f, "/admin/audit-logs?action=escalation.&page_size=50").json()["items"]}
    assert {"escalation.created", "escalation.escalated", "escalation.resolved"} <= acts
    # board members have no escalation inbox
    assert api.get(api.login("orgco", "board2@orgco.com"), "/escalations?box=inbox").status_code == 403
