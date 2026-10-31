"""Employee lifecycle: history, promotion, transfer, probation, suspension, resignation, offboarding, return, org chart."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import User
from app.tenancy.manager import tenants
from tests.conftest import PW

TODAY = datetime.now(timezone.utc).date()


def tdb(slug="lifeco"):
    with platform_session() as pdb:
        company = pdb.scalar(select(Company).where(Company.slug == slug))
        pdb.expunge(company)
    return tenants.session_for(company)


def set_user(email, **fields):
    with tdb() as db:
        u = db.scalar(select(User).where(User.email == email))
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()


@pytest.fixture(scope="module")
def co(api):
    api.make_company("lifeco")
    f = api.login("lifeco", "founder@lifeco.com")
    eng = api.post(f, "/departments", {"name": "Engineering"}).json()
    sales = api.post(f, "/departments", {"name": "Sales"}).json()
    other = api.post(f, "/branches", {"name": "North", "code": "NTH"}).json()
    hr = api.add_user(f, "hr@lifeco.com", "hr")
    hr_n = api.add_user(f, "hrn@lifeco.com", "hr")
    mgr = api.add_user(f, "mgr@lifeco.com", "manager", department_id=eng["id"])
    mgr2 = api.add_user(f, "mgr2@lifeco.com", "manager")
    people = {f"e{i}": api.add_user(f, f"e{i}@lifeco.com", "employee", manager_id=mgr["id"], department_id=eng["id"]) for i in range(1, 11)}
    people["n1"] = api.add_user(f, "n1@lifeco.com", "employee")
    api.post(f, f"/branches/{other['id']}/members", {"user_ids": [hr_n["id"], people["n1"]["id"]]})
    api.post(f, "/board/members", {"email": "board@lifeco.com", "full_name": "Board Person", "password": PW, "designation": "Director", "permissions": ["analytics.view"]})
    tok = {n: api.login("lifeco", f"{n}@lifeco.com") for n in ("hr", "hrn", "mgr", "mgr2", *people)}
    tok["board"] = api.login("lifeco", "board@lifeco.com")
    ids = {"hr": hr["id"], "hrn": hr_n["id"], "mgr": mgr["id"], "mgr2": mgr2["id"], **{n: p["id"] for n, p in people.items()}}
    for n in ("hr", "hrn", "mgr", "mgr2", *people):
        set_user(f"{n}@lifeco.com", hire_date=date(2024, 1, 1))
    return {"f": f, "tok": tok, "ids": ids, "eng": eng["id"], "sales": sales["id"], "north": other["id"]}


def life(api, co, who, viewer="hr"):
    r = api.get(co["tok"][viewer] if viewer != "f" else co["f"], f"/employees/{co['ids'][who]}/lifecycle")
    assert r.status_code == 200, r.text
    return r.json()


def kinds(api, co, who, viewer="hr"):
    return [e["kind"] for e in life(api, co, who, viewer)["items"]]


def post(api, co, who, action, body=None, by="hr"):
    return api.post(co["f"] if by == "f" else co["tok"][by], f"/employees/{co['ids'][who]}/lifecycle/{action}", body or {})


# ------------------------------------------------------------------------------ history & access

def test_history_starts_with_joining_and_is_private(api, co):
    assert kinds(api, co, "e1") == ["joined"]
    assert api.get(co["tok"]["e1"], f"/employees/{co['ids']['e1']}/lifecycle").status_code == 200        # the person
    assert api.get(co["tok"]["mgr"], f"/employees/{co['ids']['e1']}/lifecycle").status_code == 200       # their line manager
    for who in ("e2", "mgr2", "board", "hrn"):                                                            # colleague, other manager, board, other branch's HR
        assert api.get(co["tok"][who], f"/employees/{co['ids']['e1']}/lifecycle").status_code in (403, 404), who
    first = life(api, co, "e1")
    assert first["can_manage"] is True and life(api, co, "e1", "e1")["can_manage"] is False
    assert first["items"][0]["by"] == "Founder lifeco"


def test_only_hr_and_founders_run_lifecycle_actions(api, co):
    for who in ("e1", "mgr", "e2"):
        t = co["tok"][who]
        for action, body in (("promotion", {"designation": "Boss"}), ("transfer", {"department_id": co["sales"]}), ("probation", {"end_date": str(TODAY)}),
                             ("confirmation", {}), ("suspend", {"reason": "because"}), ("reinstate", {}), ("reactivate", {})):
            assert api.post(t, f"/employees/{co['ids']['e3']}/lifecycle/{action}", body).status_code == 403, (who, action)
    assert post(api, co, "e3", "promotion", {"designation": "Boss"}, by="hrn").status_code in (403, 404)    # other branch's HR


# ------------------------------------------------------------------- promotion and transfer

def test_promotion_records_before_and_after(api, co):
    assert post(api, co, "e1", "promotion", {}).status_code == 400                                                   # nothing to change
    assert post(api, co, "e1", "promotion", {"designation": "Senior", "effective_date": str(TODAY + timedelta(days=3))}).status_code == 422
    assert post(api, co, "e1", "promotion", {"designation": "Senior", "effective_date": "2020-01-01"}).status_code == 422   # before joining
    r = post(api, co, "e1", "promotion", {"designation": "Senior Engineer", "job_level": "L4", "effective_date": str(TODAY - timedelta(days=2)), "note": "Great year"})
    assert r.status_code == 200
    e = next(x for x in r.json()["items"] if x["kind"] == "promoted")
    assert e["kind"] == "promoted" and e["to"] == {"designation": "Senior Engineer", "job_level": "L4"} and e["note"] == "Great year" and e["effective_date"] == str(TODAY - timedelta(days=2))
    assert api.get(co["f"], f"/employees/{co['ids']['e1']}").json()["designation"] == "Senior Engineer"
    assert api.get(co["f"], f"/employees/{co['ids']['e1']}/profile").json()["job_level"] == "L4"
    assert post(api, co, "e1", "promotion", {"designation": "Senior Engineer"}).status_code == 400                     # same title again
    assert any("role was updated" in n["title"] for n in api.get(co["tok"]["e1"], "/notifications").json()["items"])


def test_changing_a_role_is_a_founder_decision_and_ends_sessions(api, co):
    assert post(api, co, "e2", "promotion", {"role": "manager"}, by="hr").status_code == 403
    old = co["tok"]["e2"]
    r = post(api, co, "e2", "promotion", {"role": "manager", "designation": "Team lead"}, by="f")
    assert r.status_code == 200 and {e["kind"] for e in r.json()["items"]} >= {"promoted", "role_changed"}
    assert api.get(co["f"], f"/employees/{co['ids']['e2']}").json()["role"] == "manager"
    assert api.get(old, "/auth/me").status_code == 401                                                                 # the old session knew the old role
    assert post(api, co, "e2", "promotion", {"role": "employee"}, by="f").status_code == 200                           # and it can go back down
    founder_id = api.get(co["f"], "/auth/me").json()["id"]
    assert api.post(co["f"], f"/employees/{founder_id}/lifecycle/promotion", {"role": "employee"}).status_code == 403


def test_transfers_record_one_event_per_change(api, co):
    uid = co["ids"]["e4"]
    assert post(api, co, "e4", "transfer", {}).status_code == 422
    assert post(api, co, "e4", "transfer", {"department_id": 99999}).status_code == 400
    assert post(api, co, "e4", "transfer", {"manager_id": uid}).status_code == 400                                     # not their own manager
    assert post(api, co, "e4", "transfer", {"department_id": co["eng"]}).status_code == 400                             # already there
    r = post(api, co, "e4", "transfer", {"department_id": co["sales"], "manager_id": co["ids"]["mgr2"], "note": "Joins the sales team"})
    assert r.status_code == 200
    items = r.json()["items"][:2]
    assert {e["kind"] for e in items} == {"department_changed", "manager_changed"}
    dept = next(e for e in items if e["kind"] == "department_changed")
    assert dept["from"]["name"] == "Engineering" and dept["to"]["name"] == "Sales"
    mgr = next(e for e in items if e["kind"] == "manager_changed")
    assert mgr["from"]["name"].startswith("Mgr") and mgr["to"]["id"] == co["ids"]["mgr2"]
    got = api.get(co["f"], f"/employees/{uid}").json()
    assert got["department_id"] == co["sales"] and got["manager_id"] == co["ids"]["mgr2"]
    assert post(api, co, "e4", "transfer", {"clear_manager": True}).status_code == 200
    assert api.get(co["f"], f"/employees/{uid}").json()["manager_id"] is None
    # a manager cannot report to their own report (cycle)
    cyc = post(api, co, "mgr2", "transfer", {"manager_id": co["ids"]["e1"]}, by="f")
    assert cyc.status_code == 200                                                                                       # e1 does not report to mgr2, so this is fine...
    loop = post(api, co, "e1", "transfer", {"manager_id": co["ids"]["mgr2"]}, by="f")
    assert loop.status_code == 400 and "cycle" in loop.json()["error"]["message"]                                      # ...but now the reverse would be a loop
    assert any("Employee moved" in n["title"] for n in api.get(co["tok"]["mgr2"], "/notifications").json()["items"])


def test_branch_transfers_are_founder_only_and_keep_the_reporting_line_valid(api, co):
    uid = co["ids"]["e5"]
    assert post(api, co, "e5", "transfer", {"branch_id": co["north"]}, by="hr").status_code == 403
    ok = post(api, co, "e5", "transfer", {"branch_id": co["north"]}, by="f")
    assert ok.status_code == 200 and [e["kind"] for e in ok.json()["items"][:1]] == ["branch_changed"]
    assert ok.json()["items"][0]["to"]["name"] == "North" and ok.json()["items"][0]["from"] is None
    assert api.get(co["f"], f"/employees/{uid}").json()["branch_id"] == co["north"]
    south = api.post(co["f"], "/branches", {"name": "South", "code": "STH"}).json()
    ms = api.add_user(co["f"], "ms@lifeco.com", "manager")
    api.post(co["f"], f"/branches/{south['id']}/members", {"user_ids": [ms["id"]]})
    wrong = post(api, co, "e5", "transfer", {"manager_id": ms["id"]}, by="f")
    assert wrong.status_code == 400 and "same branch" in wrong.json()["error"]["message"]                              # the manager must work in the person's branch


def test_edits_on_the_employee_form_are_recorded_too(api, co):
    uid = co["ids"]["e6"]
    assert api.patch(co["f"], f"/employees/{uid}", {"department_id": co["sales"], "designation": "Account executive"}).status_code == 200
    ks = kinds(api, co, "e6")
    assert "department_changed" in ks and "promoted" in ks
    assert api.patch(co["f"], f"/employees/{uid}", {"phone": "+1 555 0100"}).status_code == 200
    assert kinds(api, co, "e6") == ks                                                                                    # unrelated edits add nothing


# ---------------------------------------------------------------- probation and confirmation

def test_probation_and_confirmation(api, co):
    uid = co["ids"]["e7"]
    assert post(api, co, "e7", "probation", {"end_date": "2020-01-01"}).status_code == 422                               # before joining
    end = TODAY + timedelta(days=10)
    assert post(api, co, "e7", "probation", {"end_date": str(end)}).status_code == 200
    assert post(api, co, "e7", "probation", {"end_date": str(end)}).status_code == 400
    ext = post(api, co, "e7", "probation", {"end_date": str(end + timedelta(days=30)), "note": "Extended after review"}).json()["items"][0]
    assert ext["kind"] == "probation_set" and ext["from"]["end_date"] == str(end) and ext["note"] == "Extended after review"
    due = api.get(co["tok"]["hr"], "/lifecycle/due?days=60").json()
    assert any(p["user_id"] == uid and p["date"] == str(end + timedelta(days=30)) for p in due["probation"])
    assert not any(p["user_id"] == uid for p in api.get(co["tok"]["hr"], "/lifecycle/due?days=5").json()["probation"])    # not yet inside a 5-day window
    assert api.get(co["tok"]["mgr"], "/lifecycle/due").status_code == 403
    assert post(api, co, "e7", "confirmation", {"effective_date": str(TODAY + timedelta(days=1))}).status_code == 422
    c = post(api, co, "e7", "confirmation", {"note": "Passed probation"})
    assert c.status_code == 200 and c.json()["items"][0]["kind"] == "confirmed" and c.json()["state"]["confirmation_date"] == str(TODAY)
    assert post(api, co, "e7", "confirmation", {}).status_code == 409
    assert post(api, co, "e7", "probation", {"end_date": str(TODAY + timedelta(days=5))}).status_code == 409
    assert not any(p["user_id"] == uid for p in api.get(co["tok"]["hr"], "/lifecycle/due?days=90").json()["probation"])     # confirmed: off the worklist
    assert any("confirmed" in n["title"] for n in api.get(co["tok"]["e7"], "/notifications").json()["items"])


# ---------------------------------------------------------------------------- suspension

def test_suspension_blocks_sign_in_at_once_and_is_internal(api, co):
    t = co["tok"]["e8"]
    assert api.get(t, "/auth/me").status_code == 200
    assert post(api, co, "e8", "suspend", {"reason": "x"}).status_code == 422
    assert post(api, co, "e8", "suspend", {"reason": "Investigation", "until": str(TODAY - timedelta(days=1))}).status_code == 422
    r = post(api, co, "e8", "suspend", {"reason": "Pending an investigation", "until": str(TODAY + timedelta(days=14))})
    assert r.status_code == 200 and r.json()["user"]["status"] == "suspended"
    assert api.get(t, "/auth/me").status_code == 401                                                                   # open sessions end now
    assert api.c.post("/api/v1/auth/login", json={"company_slug": "lifeco", "email": "e8@lifeco.com", "password": PW}).status_code == 401
    assert post(api, co, "e8", "suspend", {"reason": "twice over"}).status_code == 409
    assert "suspended" in kinds(api, co, "e8", "hr") and "suspended" not in kinds(api, co, "e8", "mgr")                # the manager does not see why
    assert post(api, co, "e8", "reinstate", {"note": "Cleared"}).status_code == 200
    assert api.login("lifeco", "e8@lifeco.com")
    assert post(api, co, "e8", "reinstate", {}).status_code == 409
    ks = kinds(api, co, "e8")
    assert ks[:2] == ["reinstated", "suspended"]
    assert post(api, co, "hr", "suspend", {"reason": "myself again"}, by="hr").status_code == 400                       # nobody suspends themselves
    founder_id = api.get(co["f"], "/auth/me").json()["id"]
    assert api.post(co["tok"]["hr"], f"/employees/{founder_id}/lifecycle/suspend", {"reason": "a founder"}).status_code == 403
    assert api.post(co["f"], f"/employees/{founder_id}/lifecycle/suspend", {"reason": "myself"}).status_code == 400


def test_a_suspended_person_is_still_in_payroll(api, co):
    f, uid = co["f"], co["ids"]["e9"]
    comp = api.post(f, f"/payroll/compensation/{uid}", {"effective_from": "2025-01-01", "basic": 2000})
    assert comp.status_code == 201
    post(api, co, "e9", "suspend", {"reason": "Paid suspension while a review runs"})
    run = api.post(f, "/payroll/runs", {"year": TODAY.year, "month": TODAY.month}).json()
    assert uid in [s["user_id"] for s in api.get(f, f"/payroll/runs/{run['id']}").json()["payslips"]]
    api.post(f, f"/payroll/runs/{run['id']}/cancel")
    post(api, co, "e9", "reinstate", {})


# ------------------------------------------------------------------------------ resignation

def test_resignation_by_the_person_and_on_their_behalf(api, co):
    f, uid = co["f"], co["ids"]["e10"]
    api.patch(co["tok"]["hr"], f"/employees/{uid}/profile", {"notice_period_days": 30})
    me = co["tok"]["e10"]
    assert api.post(me, f"/employees/{uid}/lifecycle/resignation", {"last_working_date": str(TODAY - timedelta(days=1))}).status_code == 422
    assert api.post(co["tok"]["e1"], f"/employees/{uid}/lifecycle/resignation", {"last_working_date": str(TODAY + timedelta(days=30))}).status_code in (403, 404)   # a colleague
    assert api.post(co["tok"]["mgr"], f"/employees/{uid}/lifecycle/resignation", {"last_working_date": str(TODAY + timedelta(days=30))}).status_code == 403    # not even the manager
    last = TODAY + timedelta(days=12)
    r = api.post(me, f"/employees/{uid}/lifecycle/resignation", {"last_working_date": str(last), "reason": "Moving abroad"})
    assert r.status_code == 200 and r.json()["warning"].startswith("This is shorter than the 30-day notice")
    assert r.json()["state"]["resigned"] is True and r.json()["state"]["last_working_date"] == str(last)
    assert r.json()["items"][0]["to"]["shorter_than_notice"] is True
    assert api.post(me, f"/employees/{uid}/lifecycle/resignation", {"last_working_date": str(last)}).status_code == 409
    assert any("Resignation" in n["title"] for n in api.get(co["tok"]["mgr"], "/notifications").json()["items"])
    assert any("Resignation" in n["title"] for n in api.get(co["tok"]["hr"], "/notifications").json()["items"])
    assert any(x["user_id"] == uid and x["date"] == str(last) for x in api.get(co["tok"]["hr"], "/lifecycle/due?days=30").json()["leaving"])
    w = api.post(me, f"/employees/{uid}/lifecycle/resignation/withdraw", {"note": "Changed my mind"})
    assert w.status_code == 200 and w.json()["state"]["resigned"] is False and w.json()["state"]["last_working_date"] is None
    assert api.post(me, f"/employees/{uid}/lifecycle/resignation/withdraw", {}).status_code == 409
    assert kinds(api, co, "e10")[:2] == ["resignation_withdrawn", "resignation_submitted"]
    # HR records one on someone's behalf, and it can be resubmitted after a withdrawal
    assert post(api, co, "e10", "resignation", {"last_working_date": str(TODAY + timedelta(days=40)), "reason": "Told HR in person"}).status_code == 200
    assert api.get(f, f"/employees/{uid}/lifecycle").json()["state"]["resigned"] is True
    co["resigned"] = "e10"


# ------------------------------------------------------------------ leaving and coming back

def test_offboarding_exit_clearance_and_return(api, co):
    f, uid = co["f"], co["ids"]["e10"]
    t = co["tok"]["e10"]
    off = api.post(co["tok"]["hr"], f"/employees/{uid}/offboard", {"reason": "Resigned, notice served"})
    assert off.status_code == 200
    assert api.get(t, "/auth/me").status_code == 401
    ev = life(api, co, "e10")
    assert ev["items"][0]["kind"] == "offboarded" and ev["items"][0]["note"] == "Resigned, notice served"
    assert ev["exit_clearance"] == {"done": 0, "total": 5, "cleared": False}
    assert any(x["user_id"] == uid for x in api.get(co["tok"]["hr"], "/lifecycle/due").json()["exit_clearance"])
    items = api.get(co["tok"]["hr"], f"/employees/{uid}/checklist").json()["items"]
    off_items = [i for i in items if i["kind"] == "offboarding"]
    for i in off_items[:-1]:
        api.patch(co["tok"]["hr"], f"/checklist/{i['id']}", {"done": True})
    assert "exit_cleared" not in kinds(api, co, "e10")
    api.patch(co["tok"]["hr"], f"/checklist/{off_items[-1]['id']}", {"done": True})
    assert kinds(api, co, "e10").count("exit_cleared") == 1
    api.patch(co["tok"]["hr"], f"/checklist/{off_items[0]['id']}", {"done": False})
    api.patch(co["tok"]["hr"], f"/checklist/{off_items[0]['id']}", {"done": True})
    assert kinds(api, co, "e10").count("exit_cleared") == 1                                                            # recorded once
    assert life(api, co, "e10")["exit_clearance"]["cleared"] is True
    assert not any(x["user_id"] == uid for x in api.get(co["tok"]["hr"], "/lifecycle/due").json()["exit_clearance"])

    # coming back
    assert post(api, co, "e1", "reactivate", {}).status_code == 409                                                    # still employed
    assert api.post(co["tok"]["mgr"], f"/employees/{uid}/lifecycle/reactivate", {}).status_code == 403
    back = post(api, co, "e10", "reactivate", {"note": "Rehired after a year", "hire_date": str(TODAY)})
    assert back.status_code == 200 and back.json()["user"]["status"] == "active" and back.json()["state"]["last_working_date"] is None
    assert back.json()["items"][0]["kind"] == "reactivated"
    assert {"joined", "resignation_submitted", "offboarded", "reactivated"} <= set(kinds(api, co, "e10"))              # the whole story is still there
    assert api.login("lifeco", "e10@lifeco.com")
    assert api.get(co["f"], f"/employees/{uid}").json()["hire_date"] == str(TODAY)
    assert post(api, co, "e10", "reactivate", {}).status_code == 409


# ---------------------------------------------------------------------------- feed & org chart

def test_company_feed_is_scoped(api, co):
    all_ = api.get(co["tok"]["hr"], "/lifecycle/events?days=30&page_size=100").json()
    assert all_["total"] >= 10 and "employee" in all_["items"][0]
    only = api.get(co["tok"]["hr"], "/lifecycle/events?kind=resignation_submitted&days=30").json()["items"]
    assert only and {e["kind"] for e in only} == {"resignation_submitted"}
    branch = api.get(co["tok"]["hrn"], "/lifecycle/events?days=3650&page_size=100").json()["items"]
    assert branch and {e["employee"] for e in branch} <= {"N1 Test", "Hrn Test", "E5 Test"}                                        # only their branch's people
    assert api.get(co["tok"]["mgr"], "/lifecycle/events").status_code == 403
    assert api.get(co["tok"]["e1"], "/lifecycle/events").status_code == 403
    founder_id = api.get(co["f"], "/auth/me").json()["id"]
    assert api.get(co["tok"]["hr"], f"/employees/{founder_id}/lifecycle").status_code in (403, 404)


def test_org_chart(api, co):
    chart = api.get(co["tok"]["e1"], "/org/chart").json()                                                              # every role except the board may read it
    ids = {co["ids"]["e1"], co["ids"]["mgr"]}
    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n["children"])
    flat = {n["id"]: n for n in walk(chart["roots"])}
    assert ids <= set(flat) and chart["total"] == len(flat)
    mgr = flat[co["ids"]["mgr"]]
    assert co["ids"]["e1"] in {c["id"] for c in mgr["children"]} and mgr["reports"] == len(mgr["children"]) + sum(c["reports"] for c in mgr["children"])
    assert mgr["department"] == "Engineering" and "email" not in mgr and "phone" not in mgr                            # a directory, not a data dump
    founder = next(n for n in chart["roots"] if n["role"] == "founder")
    assert founder["name"].startswith("Founder")
    gone = co["ids"]["e10"]
    assert gone in flat                                                                                                 # the rehired person is back in the tree
    assert api.get(co["tok"]["board"], "/org/chart").status_code == 403
    north = api.get(co["f"], f"/org/chart?branch_id={co['north']}").json()
    assert {n["name"] for n in walk(north["roots"])} >= {"N1 Test", "Hrn Test"} and north["total"] < chart["total"]
    sales = api.get(co["f"], f"/org/chart?department_id={co['sales']}").json()
    assert 0 < sales["total"] < chart["total"]
    api.post(co["f"], f"/employees/{co['ids']['e3']}/offboard", {})
    assert co["ids"]["e3"] not in {n["id"] for n in walk(api.get(co["f"], "/org/chart").json()["roots"])}               # leavers drop out


def test_other_companies_see_nothing(api, co):
    api.ensure_company("lifeco2")
    f2 = api.login("lifeco2", "founder@lifeco2.com")
    assert api.get(f2, f"/employees/{co['ids']['e1']}/lifecycle").status_code in (403, 404)
    assert api.get(f2, "/lifecycle/events").json()["total"] == 1                                                         # only its own founder's "joined"
    assert [n["name"] for n in api.get(f2, "/org/chart").json()["roots"]] == ["Founder lifeco2"]
    assert api.post(f2, f"/employees/{co['ids']['e1']}/lifecycle/suspend", {"reason": "cross tenant"}).status_code in (403, 404)


@pytest.mark.parametrize("viewer", ["e1", "mgr", "hr", "f"])
def test_org_chart_links_exactly_the_records_the_viewer_may_open(api, co, viewer):
    tok = co["f"] if viewer == "f" else co["tok"][viewer]
    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n["children"])
    nodes = list(walk(api.get(tok, "/org/chart").json()["roots"]))
    assert nodes
    for n in nodes:
        assert n["can_open"] is (api.get(tok, f"/employees/{n['id']}").status_code == 200), (viewer, n["name"])
    if viewer == "e1":
        assert [n["name"] for n in nodes if n["can_open"]] == [next(n["name"] for n in nodes if n["id"] == co["ids"]["e1"])]  # an employee can open only their own
