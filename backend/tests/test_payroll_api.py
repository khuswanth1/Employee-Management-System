"""Payroll through the API: access control, versioned pay, runs from leave/attendance, approval workflow, frozen payslips, isolation."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import Attendance, AuditLog, LeaveRequest, LeaveType, User
from app.tenancy.manager import tenants
from tests.conftest import PW

# January 2026: 22 Monday-Friday working days (Jan 1 is a Thursday); 21 Sunday-Thursday days.
JAN = (2026, 1)


def tdb(slug="payco"):
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
    api.make_company("payco")
    f = api.login("payco", "founder@payco.com")
    gulf = api.post(f, "/branches", {"name": "Gulf", "code": "GLF", "working_days": ["sun", "mon", "tue", "wed", "thu"]}).json()
    hr = api.add_user(f, "hr@payco.com", "hr")
    hr_b = api.add_user(f, "hrb@payco.com", "hr")
    mgr = api.add_user(f, "mgr@payco.com", "manager")
    people = {n: api.add_user(f, f"{n}@payco.com", "employee", manager_id=mgr["id"]) for n in ("e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8")}
    people["g1"] = api.add_user(f, "g1@payco.com", "employee")
    api.post(f, f"/branches/{gulf['id']}/members", {"user_ids": [hr_b["id"], people["g1"]["id"]]})
    api.post(f, "/board/members", {"email": "board@payco.com", "full_name": "Board Person", "password": PW, "designation": "Director", "permissions": ["analytics.view"]})
    names = ["hr", "hrb", "mgr", *people]
    tok = {n: api.login("payco", f"{n}@payco.com") for n in names}
    tok["board"] = api.login("payco", "board@payco.com")
    ids = {"hr": hr["id"], "hrb": hr_b["id"], "mgr": mgr["id"], **{n: p["id"] for n, p in people.items()}}
    for n in ("hr", "hrb", "mgr", *people):          # everyone was hired before the periods under test
        set_user(f"{n}@payco.com", hire_date=date(2025, 1, 1))
    set_user("founder@payco.com", hire_date=date(2025, 1, 1))
    comps = {}
    for body in (
        {"code": "HRA", "name": "Housing allowance", "kind": "earning", "calc": "percent_of_basic", "default_value": 40},
        {"code": "TRAVEL", "name": "Travel allowance", "kind": "earning", "calc": "fixed", "default_value": 200},
        {"code": "RETIRE", "name": "Retirement contribution", "kind": "deduction", "calc": "percent_of_basic", "default_value": 12, "note": "example rate: set from your local rules"},
        {"code": "LEVY", "name": "Income levy", "kind": "deduction", "calc": "percent_of_gross", "default_value": 5},
        {"code": "HUGE", "name": "Large recovery", "kind": "deduction", "calc": "fixed", "default_value": 100000},
    ):
        r = api.post(f, "/payroll/components", body)
        assert r.status_code == 201, r.text
        comps[body["code"]] = r.json()
    return {"f": f, "tok": tok, "ids": ids, "comps": comps}


def give_pay(api, co, who, basic=3000, lines=("HRA", "TRAVEL", "RETIRE", "LEVY"), effective="2025-01-01", by="f"):
    tok = co["f"] if by == "f" else co["tok"][by]
    body = {"effective_from": effective, "basic": basic, "lines": [{"component_id": co["comps"][c]["id"], "value": co["comps"][c]["default_value"]} for c in lines]}
    r = api.post(tok, f"/payroll/compensation/{co['ids'][who]}", body)
    assert r.status_code == 201, r.text
    return r.json()


def new_run(api, co, year, month, by="f"):
    r = api.post(co["f"] if by == "f" else co["tok"][by], "/payroll/runs", {"year": year, "month": month})
    assert r.status_code == 201, r.text
    return r.json()


def slip(api, co, run_id, who):
    for s in api.get(co["f"], f"/payroll/runs/{run_id}").json()["payslips"]:
        if s["user_id"] == co["ids"][who]:
            return api.get(co["f"], f"/payroll/payslips/{s['id']}").json()
    raise AssertionError(f"no payslip for {who}")


def line(s, code):
    return next(ln["amount"] for ln in s["lines"] if ln["code"] == code)


# ------------------------------------------------------------------------------ access

def test_only_payroll_staff_can_touch_payroll(api, co):
    for who in ("mgr", "e1", "board"):
        t = co["tok"][who]
        for method, url in (("get", "/payroll/components"), ("get", "/payroll/runs"), ("get", "/payroll/compensation"), ("get", "/payroll/reports/summary")):
            assert getattr(api, method)(t, url).status_code == 403, (who, url)
        assert api.post(t, "/payroll/runs", {"year": 2026, "month": 1}).status_code == 403
        assert api.post(t, "/payroll/components", {"code": "X1", "name": "X one", "kind": "earning"}).status_code == 403
        assert api.post(t, f"/payroll/compensation/{co['ids']['e1']}", {"effective_from": "2026-01-01", "basic": 100}).status_code == 403
    assert api.get(co["tok"]["e1"], "/payroll/my-payslips").json() == {"items": []}   # everyone may read their own


def test_hr_cannot_see_or_set_pay_of_founders_hr_or_themselves(api, co):
    hr = co["tok"]["hr"]
    founder_id = api.get(co["f"], "/auth/me").json()["id"]
    for uid in (founder_id, co["ids"]["hr"], co["ids"]["hrb"]):
        assert api.get(hr, f"/payroll/compensation/{uid}").status_code == 404
        assert api.post(hr, f"/payroll/compensation/{uid}", {"effective_from": "2026-01-01", "basic": 1}).status_code == 404
    assert api.get(co["f"], f"/payroll/compensation/{co['ids']['hr']}").status_code == 200       # the founder can
    listed = {r["user_id"] for r in api.get(hr, "/payroll/compensation?page_size=100").json()["items"]}
    assert co["ids"]["e1"] in listed and not ({founder_id, co["ids"]["hr"]} & listed)


def test_branch_hr_is_limited_to_their_branch_and_cannot_run_payroll(api, co):
    hrb = co["tok"]["hrb"]
    assert api.get(hrb, f"/payroll/compensation/{co['ids']['e1']}").status_code == 404           # another branch
    assert api.get(hrb, f"/payroll/compensation/{co['ids']['g1']}").status_code == 200
    assert api.post(hrb, "/payroll/runs", {"year": 2026, "month": 1}).status_code == 403
    assert api.post(hrb, "/payroll/components", {"code": "BR1", "name": "Branch made", "kind": "earning"}).status_code == 403
    assert api.get(hrb, "/payroll/components").status_code == 200
    assert api.post(hrb, f"/payroll/compensation/{co['ids']['g1']}", {"effective_from": "2025-06-01", "basic": 2500}).status_code == 201


# ------------------------------------------------------------------------- components

def test_component_validation(api, co):
    f = co["f"]
    ok = {"code": "BONUSX", "name": "Special bonus", "kind": "earning", "calc": "fixed", "default_value": 50}
    assert api.post(f, "/payroll/components", {**ok, "calc": "percent_of_gross"}).status_code == 422                # an earning cannot be % of gross
    assert api.post(f, "/payroll/components", {**ok, "calc": "percent_of_basic", "default_value": 101}).status_code == 422
    assert api.post(f, "/payroll/components", {**ok, "default_value": 10.005}).status_code == 422                    # three decimals
    assert api.post(f, "/payroll/components", {**ok, "code": "bad code!"}).status_code == 422
    assert api.post(f, "/payroll/components", {**ok, "code": "hra"}).status_code == 409                              # codes are case-insensitive unique
    assert api.post(f, "/payroll/components", {**ok, "code": "BASIC"}).status_code == 409                            # reserved
    assert api.post(f, "/payroll/components", {**ok, "name": "housing ALLOWANCE"}).status_code == 409
    made = api.post(f, "/payroll/components", ok).json()
    assert made["default_value"] == 50 and made["code"] == "BONUSX"
    assert api.patch(f, f"/payroll/components/{made['id']}", {**ok, "name": "Special bonus", "default_value": 75, "cap": 60}).json()["cap"] == 60
    unused = co["comps"]["HUGE"]                                                                                   # nobody uses this one yet: its type may change
    assert api.patch(f, f"/payroll/components/{unused['id']}", {"code": "HUGE", "name": "Large recovery", "kind": "deduction", "calc": "fixed", "default_value": 100000}).status_code == 200


def test_a_component_in_use_keeps_its_type(api, co):
    give_pay(api, co, "e8", lines=("HRA",))
    hra = co["comps"]["HRA"]
    r = api.patch(co["f"], f"/payroll/components/{hra['id']}", {"code": "HRA", "name": "Housing allowance", "kind": "earning", "calc": "fixed", "default_value": 10})
    assert r.status_code == 409
    renamed = api.patch(co["f"], f"/payroll/components/{hra['id']}", {"code": "HRA", "name": "Housing allowance", "kind": "earning", "calc": "percent_of_basic",
                                                                      "default_value": 40, "note": "reviewed"})
    assert renamed.status_code == 200


# ---------------------------------------------------------------------- pay structures

def test_pay_structures_are_versioned_and_validated(api, co):
    f, uid = co["f"], co["ids"]["e7"]
    url = f"/payroll/compensation/{uid}"
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 0}).status_code == 422
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 100.123}).status_code == 422
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 100, "lines": [{"component_id": 9999, "value": 1}]}).status_code == 400
    hra = co["comps"]["HRA"]["id"]
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 100, "lines": [{"component_id": hra, "value": 1}, {"component_id": hra, "value": 2}]}).status_code == 400
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 100, "lines": [{"component_id": hra, "value": 150}]}).status_code == 422   # 150%
    v1 = api.post(f, url, {"effective_from": "2025-01-01", "basic": 2000, "note": "joining"}).json()
    assert api.post(f, url, {"effective_from": "2025-01-01", "basic": 2100}).status_code == 409
    v2 = api.post(f, url, {"effective_from": "2025-07-01", "basic": 2400.50, "lines": [{"component_id": hra, "value": 30}]}).json()
    hist = api.get(f, url).json()["items"]
    assert [h["id"] for h in hist] == [v2["id"], v1["id"]] and hist[0]["basic"] == 2400.5 and hist[1]["basic"] == 2000   # nothing was overwritten
    assert hist[0]["lines"][0]["value"] == 30 and hist[0]["lines"][0]["code"] == "HRA"
    with tdb() as db:  # the audit trail records that pay changed, never the amounts
        detail = " ".join(str(a.detail) for a in db.scalars(select(AuditLog).where(AuditLog.action.like("payroll.%"))))
    assert "2400" not in detail and "2000" not in detail


# ------------------------------------------------------------------------ run figures

def test_run_figures_from_pay_leave_and_the_branch_week(api, co):
    f, ids = co["f"], co["ids"]
    for who in ("e1", "e2", "e3", "e4", "e5"):                                                     # e6 deliberately has no structure yet
        give_pay(api, co, who, effective="2025-06-01")
    # g1 already has a structure from the branch HR test (2500 basic, no lines)
    set_user("e4@payco.com", hire_date=date(2026, 1, 12))                                          # joins mid-month
    set_user("e5@payco.com", is_active=False, status="offboarded", offboarded_at=datetime(2026, 1, 9, 12, tzinfo=timezone.utc))
    with tdb() as db:
        unpaid = db.scalar(select(LeaveType).where(LeaveType.name == "Unpaid Leave"))
        annual = db.scalar(select(LeaveType).where(LeaveType.name == "Annual Leave"))
        for who, lt, a, b in (("e2", unpaid, date(2026, 1, 5), date(2026, 1, 6)), ("e3", annual, date(2026, 1, 12), date(2026, 1, 14))):
            uid = db.scalar(select(User.id).where(User.email == f"{who}@payco.com"))
            db.add(LeaveRequest(user_id=uid, leave_type_id=lt.id, start_date=a, end_date=b, days=(b - a).days + 1, status="approved"))
        db.commit()
    run = new_run(api, co, *JAN)
    assert run["status"] == "draft" and [(x["user_id"], x["reason"]) for x in run["skipped"] if x["user_id"] == ids["e6"]] == [(ids["e6"], "no pay structure set up")]

    full = slip(api, co, run["id"], "e1")
    assert full["facts"]["scheduled_days"] == 22 and full["facts"]["payable_days"] == "22"
    assert (full["basic"], line(full, "HRA"), line(full, "TRAVEL"), full["gross"]) == (3000, 1200, 200, 4400)
    assert (line(full, "RETIRE"), line(full, "LEVY"), full["deductions"], full["net"]) == (360, 220, 580, 3820)

    short = slip(api, co, run["id"], "e2")                                                          # 2 unpaid days of 22
    assert short["facts"]["unpaid_leave_days"] == "2" and short["facts"]["payable_days"] == "20"
    assert (short["basic"], line(short, "HRA"), line(short, "TRAVEL"), short["gross"]) == (2727.27, 1090.91, 181.82, 4000)
    assert (line(short, "RETIRE"), line(short, "LEVY"), short["net"]) == (327.27, 200, 3472.73)

    paid = slip(api, co, run["id"], "e3")                                                           # 3 days of paid annual leave cost nothing
    assert paid["facts"]["paid_leave_days"] == "3" and paid["net"] == 3820

    joiner = slip(api, co, run["id"], "e4")                                                         # first day Monday 12 January: 15 working days
    assert joiner["facts"]["employed_days"] == 15 and joiner["basic"] == 2045.45
    leaver = slip(api, co, run["id"], "e5")                                                         # last day Friday 9 January: 7 working days
    assert leaver["facts"]["employed_days"] == 7 and leaver["basic"] == 954.55

    gulf = slip(api, co, run["id"], "g1")                                                           # Sunday-Thursday week: 21 days in January
    assert gulf["facts"]["scheduled_days"] == 21 and gulf["basic"] == 2500 and gulf["net"] == 2500

    detail = api.get(f, f"/payroll/runs/{run['id']}").json()
    assert detail["totals"]["payslips"] == len(detail["payslips"]) == 8 and detail["totals"]["net"] == round(sum(s["net"] for s in detail["payslips"]), 2)
    assert detail["policy"]["attendance_basis"] == "ignore" and detail["by_department"]
    assert api.post(f, "/payroll/runs", {"year": 2026, "month": 1}).status_code == 409             # one run per month
    assert api.post(f, "/payroll/runs", {"year": 2099, "month": 1}).status_code == 400            # not for the future
    assert api.post(f, "/payroll/runs", {"year": 2026, "month": 13}).status_code == 422
    co["jan"] = run["id"]


# ------------------------------------------------------------------------ the workflow

def test_adjustments_then_submit_then_a_different_person_approves(api, co):
    f, hr, rid = co["f"], co["tok"]["hr"], co["jan"]
    sid = next(s["id"] for s in api.get(f, f"/payroll/runs/{rid}").json()["payslips"] if s["user_id"] == co["ids"]["e1"])
    assert api.post(co["tok"]["e1"], f"/payroll/payslips/{sid}/adjustments", {"name": "x", "kind": "earning", "amount": 1}).status_code == 403
    assert api.post(hr, f"/payroll/payslips/{sid}/adjustments", {"name": "Spot bonus", "kind": "earning", "amount": 0}).status_code == 422
    bonus = api.post(hr, f"/payroll/payslips/{sid}/adjustments", {"name": "Spot bonus", "kind": "earning", "amount": 500}).json()
    assert bonus["gross"] == 4900 and bonus["net"] == 4320 and bonus["id"] == sid                  # same payslip, in place
    advance = api.post(hr, f"/payroll/payslips/{sid}/adjustments", {"name": "Advance recovery", "kind": "deduction", "amount": 100.5}).json()
    assert advance["deductions"] == 680.5 and advance["net"] == 4219.5
    assert api.delete(hr, f"/payroll/payslips/{sid}/adjustments/{next(x['id'] for x in advance['lines'] if x['code'] == 'RETIRE')}").status_code == 404   # only adjustments
    adj = next(x for x in advance["lines"] if x["name"] == "Spot bonus")
    assert api.delete(hr, f"/payroll/payslips/{sid}/adjustments/{adj['id']}").json()["net"] == 3719.5
    api.post(hr, f"/payroll/payslips/{sid}/adjustments", {"name": "Spot bonus", "kind": "earning", "amount": 500})
    assert api.post(hr, f"/payroll/runs/{rid}/recalculate").status_code == 200                       # adjustments survive a recalculation
    assert slip(api, co, rid, "e1")["net"] == 4219.5

    assert api.post(hr, f"/payroll/runs/{rid}/approve").status_code == 409                          # not submitted yet
    assert api.post(hr, f"/payroll/runs/{rid}/submit").json()["status"] == "processed"
    assert api.post(hr, f"/payroll/runs/{rid}/approve").status_code == 403                          # never your own submission
    assert api.post(hr, f"/payroll/runs/{rid}/return", {"note": "check e2"}).status_code == 403
    assert api.post(hr, f"/payroll/payslips/{sid}/adjustments", {"name": "late", "kind": "earning", "amount": 1}).status_code == 409   # locked once submitted
    assert api.post(hr, f"/payroll/runs/{rid}/recalculate").status_code == 409
    assert any("awaiting approval" in n["title"] for n in api.get(f, "/notifications").json()["items"])
    back = api.post(f, f"/payroll/runs/{rid}/return", {"note": "please check e2"})
    assert back.json()["status"] == "draft"
    assert any("sent back" in n["title"] for n in api.get(hr, "/notifications").json()["items"])
    api.post(hr, f"/payroll/runs/{rid}/submit")
    assert api.get(co["tok"]["e1"], "/payroll/my-payslips").json()["items"] == []                   # nothing is visible before approval
    assert api.get(co["tok"]["e1"], f"/payroll/payslips/{sid}").status_code == 404
    ok = api.post(f, f"/payroll/runs/{rid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approved_by"]
    assert any("payslip is available" in n["title"] for n in api.get(co["tok"]["e1"], "/notifications").json()["items"])


def test_approved_payslips_are_visible_to_their_owner_only_and_frozen(api, co):
    f, rid = co["f"], co["jan"]
    mine = api.get(co["tok"]["e1"], "/payroll/my-payslips").json()["items"]
    assert len(mine) == 1 and mine[0]["year"] == 2026 and mine[0]["net"] == 4219.5
    sid = mine[0]["id"]
    own = api.get(co["tok"]["e1"], f"/payroll/payslips/{sid}")
    assert own.status_code == 200 and {ln["code"] for ln in own.json()["lines"]} >= {"BASIC", "HRA", "RETIRE", "ADJ"}
    for other in ("e2", "mgr", "board", "hrb"):                                                      # not a colleague, not the manager, not another branch's HR
        assert api.get(co["tok"][other], f"/payroll/payslips/{sid}").status_code == 404, other
    assert api.get(co["tok"]["hr"], f"/payroll/payslips/{sid}").status_code == 200
    with tdb() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "payroll.payslip_viewed")) is not None   # HR opening someone else's payslip is logged
    # frozen: later changes to pay, names, components, settings do not touch an issued payslip
    api.post(f, f"/payroll/compensation/{co['ids']['e1']}", {"effective_from": "2026-06-01", "basic": 9999})
    set_user("e1@payco.com", full_name="Renamed Person", designation="CEO")
    api.patch(f, f"/payroll/components/{co['comps']['TRAVEL']['id']}", {"code": "TRAVEL", "name": "Travel allowance", "kind": "earning", "calc": "fixed", "default_value": 999, "note": "x"})
    again = api.get(co["tok"]["e1"], f"/payroll/payslips/{sid}").json()
    assert again["net"] == 4219.5 and again["employee"] != "Renamed Person" and line(again, "TRAVEL") == 200
    # locked
    assert api.post(f, f"/payroll/runs/{rid}/recalculate").status_code == 409
    assert api.post(f, f"/payroll/runs/{rid}/cancel").status_code == 409
    assert api.post(f, f"/payroll/compensation/{co['ids']['e2']}", {"effective_from": "2026-01-15", "basic": 1}).status_code == 400   # inside an approved month
    paid = api.post(f, f"/payroll/runs/{rid}/mark-paid", {"reference": "BATCH-1"})
    assert paid.json()["status"] == "paid" and paid.json()["payment_reference"] == "BATCH-1"
    assert api.post(f, f"/payroll/runs/{rid}/mark-paid", {}).status_code == 409
    assert api.get(co["tok"]["e1"], "/payroll/my-payslips").json()["items"][0]["status"] == "paid"


def test_negative_net_pay_blocks_approval_until_fixed(api, co):
    f, hr = co["f"], co["tok"]["hr"]
    give_pay(api, co, "e6", basic=1000, lines=("HUGE",), effective="2025-06-01")
    run = new_run(api, co, 2026, 2, by="hr")
    s = slip(api, co, run["id"], "e6")
    assert s["net"] < 0 and "deductions_exceed_pay" in s["warnings"]
    assert api.post(hr, f"/payroll/runs/{run['id']}/submit").status_code == 200
    r = api.post(f, f"/payroll/runs/{run['id']}/approve")
    assert r.status_code == 400 and r.json()["error"]["code"] == "payslip_blocked"
    api.post(f, f"/payroll/runs/{run['id']}/return", {"note": "fix e6"})
    give_pay(api, co, "e6", basic=1000, lines=(), effective="2026-02-01")                            # replace the structure from February
    api.post(hr, f"/payroll/runs/{run['id']}/recalculate")
    assert slip(api, co, run["id"], "e6")["net"] == 1000
    api.post(hr, f"/payroll/runs/{run['id']}/submit")
    assert api.post(f, f"/payroll/runs/{run['id']}/approve").status_code == 200


def test_cancelled_runs_free_the_month_and_hold_no_visible_payslips(api, co):
    hr = co["tok"]["hr"]
    run = new_run(api, co, 2026, 3, by="hr")
    assert api.post(hr, f"/payroll/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert api.post(hr, f"/payroll/runs/{run['id']}/submit").status_code == 409
    again = new_run(api, co, 2026, 3, by="hr")
    assert again["id"] != run["id"]
    months = [x["month"] for x in api.get(co["tok"]["e1"], "/payroll/my-payslips").json()["items"]]
    assert 1 in months and 3 not in months                                                          # the cancelled and the unapproved month are not shown


def test_attendance_basis_and_overtime(api, co):
    f, hr = co["f"], co["tok"]["hr"]
    assert api.put(f, "/admin/settings/payroll_attendance_basis", {"value": "sometimes"}).status_code in (400, 422)
    assert api.put(f, "/admin/settings/payroll_overtime_multiplier", {"value": "9"}).status_code in (400, 422)
    give_pay(api, co, "e8", basic=2200, lines=(), effective="2026-04-01")
    with tdb() as db:
        uid = db.scalar(select(User.id).where(User.email == "e8@payco.com"))
        for d in range(1, 31):
            day = date(2026, 4, d)
            if day.weekday() < 5 and d <= 20:              # present for the first 20 days of April, nothing after
                db.add(Attendance(user_id=uid, work_date=day, check_in=datetime(2026, 4, d, 9, tzinfo=timezone.utc), check_out=datetime(2026, 4, d, 17, tzinfo=timezone.utc),
                                  status="present", day_type="workday", worked_minutes=480, break_minutes=0, late_minutes=0, early_minutes=0,
                                  overtime_minutes=60 if d == 6 else 0))
        db.commit()
    api.put(f, "/admin/settings/payroll_attendance_basis", {"value": "attendance"})
    api.put(f, "/admin/settings/payroll_overtime_multiplier", {"value": "1.5"})
    try:
        run = new_run(api, co, 2026, 4, by="hr")
        s = slip(api, co, run["id"], "e8")
        working = s["facts"]["scheduled_days"]                                                       # 22 Mon-Fri days in April 2026
        assert working == 22 and s["facts"]["payable_days"] == "14" and s["facts"]["absent_days"] == "8"   # attended 1-3, 6-10, 13-17 and 20 April
        assert s["basic"] == round(2200 * 14 / 22, 2) == 1400
        assert s["facts"]["overtime_hours"] == "1.00" and line(s, "OVERTIME") == round(2200 / (22 * 8) * 1.5, 2)
        assert run["policy"]["attendance_basis"] == "attendance" and run["policy"]["overtime_multiplier"] == "1.5"
    finally:
        api.put(f, "/admin/settings/payroll_attendance_basis", {"value": "ignore"})
        api.put(f, "/admin/settings/payroll_overtime_multiplier", {"value": "0"})
    # the run keeps the policy it was calculated with, whatever the settings say now
    assert api.get(f, f"/payroll/runs/{run['id']}").json()["policy"]["attendance_basis"] == "attendance"
    api.post(hr, f"/payroll/runs/{run['id']}/cancel")


# --------------------------------------------------------------------------- scope & reports

def test_hr_does_not_see_founder_or_hr_pay_in_runs_or_exports(api, co):
    f, hr = co["f"], co["tok"]["hr"]
    founder_id = api.get(f, "/auth/me").json()["id"]
    give_pay(api, co, "mgr", basic=5000, lines=(), effective="2025-06-01")
    with tdb() as db:                                                                                  # a structure for the founder and for HR
        from app.db.tenant_models import Compensation
        for uid, amount in ((founder_id, 900000), (co["ids"]["hr"], 700000)):
            db.add(Compensation(user_id=uid, effective_from=date(2025, 1, 1), basic_minor=amount, currency="USD"))
        db.commit()
    run = new_run(api, co, 2026, 5)
    full = api.get(f, f"/payroll/runs/{run['id']}").json()
    seen_by_hr = api.get(hr, f"/payroll/runs/{run['id']}").json()
    assert founder_id in {s["user_id"] for s in full["payslips"]} and co["ids"]["hr"] in {s["user_id"] for s in full["payslips"]}
    assert not ({founder_id, co["ids"]["hr"]} & {s["user_id"] for s in seen_by_hr["payslips"]})
    assert seen_by_hr["totals"]["net"] < full["totals"]["net"]
    csv_hr, csv_f = api.get(hr, f"/payroll/runs/{run['id']}/export.csv"), api.get(f, f"/payroll/runs/{run['id']}/export.csv")
    assert csv_hr.headers["content-type"].startswith("text/csv") and "9000.0" not in csv_hr.text and "7000.0" not in csv_hr.text
    assert "9000" in csv_f.text and "Employee code" in csv_f.text
    some_founder_slip = next(s["id"] for s in full["payslips"] if s["user_id"] == founder_id)
    assert api.get(hr, f"/payroll/payslips/{some_founder_slip}").status_code == 404
    assert api.post(hr, f"/payroll/payslips/{some_founder_slip}/adjustments", {"name": "gift", "kind": "earning", "amount": 1}).status_code == 404
    hrb = api.get(co["tok"]["hrb"], f"/payroll/runs/{run['id']}").json()                                # a branch HR sees their branch only
    assert {s["user_id"] for s in hrb["payslips"]} == {co["ids"]["g1"]}
    api.post(hr, f"/payroll/runs/{run['id']}/cancel")


def test_history_and_summary_reports(api, co):
    f, hr = co["f"], co["tok"]["hr"]
    hist = api.get(hr, f"/payroll/employees/{co['ids']['e1']}/payslips").json()["items"]
    by_month = {h["month"]: h["status"] for h in hist}
    assert by_month == {1: "paid", 2: "approved", 3: "draft"}                          # cancelled runs are left out; HR sees drafts, employees do not
    assert api.get(co["tok"]["e1"], f"/payroll/employees/{co['ids']['e1']}/payslips").status_code == 403
    assert api.get(co["tok"]["hrb"], f"/payroll/employees/{co['ids']['e1']}/payslips").status_code == 404
    rep = api.get(f, "/payroll/reports/summary?year=2026").json()
    assert [x["month"] for x in rep["months"]] == [1, 2] and rep["months"][0]["status"] == "paid"
    assert rep["totals"]["net"] == round(sum(x["net"] for x in rep["months"]), 2)
    assert api.get(hr, "/payroll/reports/summary?year=2026").json()["totals"]["net"] <= rep["totals"]["net"]


def test_other_companies_see_no_payroll(api, co):
    api.ensure_company("payco2")
    f2 = api.login("payco2", "founder@payco2.com")
    assert api.get(f2, "/payroll/runs").json()["items"] == [] and api.get(f2, "/payroll/components").json()["items"] == []
    assert api.get(f2, f"/payroll/runs/{co['jan']}").status_code == 404
    assert api.get(f2, "/payroll/payslips/1").status_code == 404
    assert api.get(f2, f"/payroll/compensation/{co['ids']['e1']}").status_code == 404
    assert api.post(f2, f"/payroll/runs/{co['jan']}/approve").status_code == 404
