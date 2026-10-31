"""Leave through the API and service layer: half days, branch weeks, ledger, revisions, delegation, accrual, carry-forward, reports."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db.tenant_models import LeaveBalance, LeaveLedger, LeaveRequest, LeaveType, User
from app.db.session import platform_session
from app.db.platform_models import Company
from app.modules.leave import service as svc
from app.tenancy.manager import tenants
from app.db.base import utcnow


def monday(weeks: int) -> date:
    """A Monday `weeks` ahead whose whole Monday-Friday week lies in one calendar year."""
    d = utcnow().date() + timedelta(days=(7 - utcnow().date().weekday()) % 7 or 7) + timedelta(weeks=weeks)
    while d.year != (d + timedelta(days=6)).year:
        d += timedelta(weeks=1)
    return d


def tdb(slug="lvco"):
    with platform_session() as pdb:
        company = pdb.scalar(select(Company).where(Company.slug == slug))
        pdb.expunge(company)
    return tenants.session_for(company)


@pytest.fixture(scope="module")
def co(api):
    api.make_company("lvco")
    f = api.login("lvco", "founder@lvco.com")
    gulf = api.post(f, "/branches", {"name": "Gulf", "code": "GLF", "working_days": ["sun", "mon", "tue", "wed", "thu"]}).json()
    ohio = api.post(f, "/branches", {"name": "Ohio", "code": "OHI"}).json()
    hr = api.add_user(f, "hr@lvco.com", "hr")
    hr_g = api.add_user(f, "hrg@lvco.com", "hr")
    hr_o = api.add_user(f, "hro@lvco.com", "hr")
    mgr = api.add_user(f, "mgr@lvco.com", "manager")
    mgr_b = api.add_user(f, "mgrb@lvco.com", "manager")
    mgrd = api.add_user(f, "mgrd@lvco.com", "manager")
    mgr_g = api.add_user(f, "mgrg@lvco.com", "manager")
    people = {f"e{i}": api.add_user(f, f"e{i}@lvco.com", "employee", manager_id=mgr["id"]) for i in range(1, 16)}
    people["b1"] = api.add_user(f, "b1@lvco.com", "employee", manager_id=mgr_b["id"])
    people["g1"] = api.add_user(f, "g1@lvco.com", "employee", manager_id=mgr_g["id"])
    people["o1"] = api.add_user(f, "o1@lvco.com", "employee")
    api.post(f, f"/branches/{gulf['id']}/members", {"user_ids": [hr_g["id"], mgr_g["id"], people["g1"]["id"]]})
    api.post(f, f"/branches/{ohio['id']}/members", {"user_ids": [hr_o["id"], people["o1"]["id"]]})
    names = ["hr", "hrg", "hro", "mgr", "mgrb", "mgrd", "mgrg", *people]
    tok = {n: api.login("lvco", f"{n}@lvco.com") for n in names}
    ids = {"hr": hr["id"], "hrg": hr_g["id"], "hro": hr_o["id"], "mgr": mgr["id"], "mgrb": mgr_b["id"], "mgrd": mgrd["id"], "mgrg": mgr_g["id"],
           **{n: p["id"] for n, p in people.items()}}
    types = {t["name"]: t for t in api.get(f, "/leave/types").json()["items"]}
    return {"f": f, "tok": tok, "ids": ids, "types": types}


def ask(api, co, who, type_name="Annual Leave", start=None, end=None, **extra):
    start = start or monday(2)
    body = {"leave_type_id": co["types"][type_name]["id"], "start_date": start.isoformat(), "end_date": (end or start).isoformat(), **extra}
    return api.post(co["tok"][who], "/leave/requests", body)


def bal(api, co, who, type_name="Annual Leave", via=None, year=None):
    """The balance for `year` (default: this year). Leave is charged to the year it starts in, so pass d.year for future dates."""
    path = "/leave/balances" if via is None else f"/leave/balances/{co['ids'][who]}"
    rows = api.get(co["tok"][via or who], path + (f"?year={year}" if year else "")).json()["items"]
    return [b for b in rows if b["leave_type"] == type_name][0]


def decide(api, co, who, rid, approved=True, note=None):
    return api.post(co["tok"][who], f"/leave/requests/{rid}/decision", {"approved": approved, "note": note})


def ledger_sum(api, co, who, type_id, year=None):
    year = year or utcnow().date().year
    rows = api.get(co["tok"][who], f"/leave/ledger?leave_type_id={type_id}&year={year}&page_size=100").json()["items"]
    return round(sum(r["days"] for r in rows), 4)


# ----------------------------------------------------------------------------- half days

def test_half_days_and_how_they_overlap(api, co):
    d = monday(2)
    first = ask(api, co, "e1", start=d, half_day="first")
    assert first.status_code == 201 and first.json()["days"] == 0.5 and first.json()["half_day"] == "first"
    assert ask(api, co, "e1", start=d, half_day="second").status_code == 201         # the other half is free
    assert ask(api, co, "e1", start=d, half_day="first").status_code == 409          # same half twice
    assert ask(api, co, "e1", start=d).status_code == 409                            # a full day over a half day
    assert ask(api, co, "e2", start=d, end=d + timedelta(days=1), half_day="first").status_code == 422   # half days are single-day
    sat = d + timedelta(days=5)
    assert ask(api, co, "e2", start=sat, half_day="first").status_code == 400        # nothing to take on a Saturday
    co["types"]["Block"] = api.post(co["f"], "/leave/types", {"name": "Block", "annual_quota": 5, "allow_half_day": False}).json()
    r = ask(api, co, "e2", "Block", start=d, half_day="first")
    assert r.status_code == 400 and "half days" in r.json()["error"]["message"]
    for rid in [first.json()["id"]]:
        assert decide(api, co, "mgr", rid).json()["status"] == "approved"
    assert bal(api, co, "e1", year=d.year)["used"] == 0.5


# ------------------------------------------------------------------- working week per branch

def test_days_are_counted_on_the_branchs_own_working_week(api, co):
    sun = monday(2) - timedelta(days=1)                                              # a Sunday
    fri = monday(2) + timedelta(days=4)
    g = ask(api, co, "g1", start=sun, end=sun + timedelta(days=6))                   # Sun..Sat in a Sunday-Thursday branch
    assert g.status_code == 201 and g.json()["days"] == 5
    assert ask(api, co, "g1", start=monday(5) + timedelta(days=4), end=monday(5) + timedelta(days=5)).status_code == 400    # Fri+Sat: weekend there
    assert ask(api, co, "e3", start=sun).status_code == 400                           # a Sunday is a weekend for a branchless person
    plain = ask(api, co, "e3", start=monday(2), end=monday(2) + timedelta(days=6))
    assert plain.json()["days"] == 5
    assert fri.weekday() == 4


def test_types_can_count_calendar_days(api, co):
    t = api.post(co["f"], "/leave/types", {"name": "Maternity", "annual_quota": 90, "count_all_days": True}).json()
    co["types"]["Maternity"] = t
    r = ask(api, co, "e4", "Maternity", start=monday(3), end=monday(3) + timedelta(days=6))
    assert r.json()["days"] == 7


def test_notice_period_and_maximum_stretch(api, co):
    api.post(co["f"], "/leave/types", {"name": "Planned", "annual_quota": 10, "min_notice_days": 10, "max_consecutive_days": 3})
    co["types"] = {t["name"]: t for t in api.get(co["f"], "/leave/types").json()["items"]}
    soon = utcnow().date() + timedelta(days=3)
    while soon.weekday() >= 5:
        soon += timedelta(days=1)
    assert "notice" in ask(api, co, "e4", "Planned", start=soon).json()["error"]["message"]
    far = monday(4)
    assert ask(api, co, "e4", "Planned", start=far, end=far + timedelta(days=3)).status_code == 400   # 4 days > 3
    assert ask(api, co, "e4", "Planned", start=far, end=far + timedelta(days=2)).status_code == 201


# ------------------------------------------------------------------- editing a pending request

def test_a_pending_request_can_be_changed_by_its_owner_only(api, co):
    d = monday(6)
    r = ask(api, co, "e5", start=d, end=d + timedelta(days=1), reason="first idea").json()
    other = ask(api, co, "e5", start=d + timedelta(days=14)).json()
    tok = co["tok"]["e5"]
    ok = api.patch(tok, f"/leave/requests/{r['id']}", {"end_date": (d + timedelta(days=4)).isoformat(), "reason": "longer"})
    assert ok.status_code == 200 and ok.json()["days"] == 5 and ok.json()["reason"] == "longer"
    assert api.patch(tok, f"/leave/requests/{r['id']}", {"end_date": (d + timedelta(days=15)).isoformat()}).status_code == 409    # clashes with the other
    assert api.patch(tok, f"/leave/requests/{r['id']}", {"end_date": (d - timedelta(days=1)).isoformat()}).status_code == 422
    assert api.patch(tok, f"/leave/requests/{r['id']}", {"end_date": (d + timedelta(weeks=20)).isoformat()}).status_code == 400   # beyond the balance
    assert api.patch(tok, f"/leave/requests/{r['id']}", {"half_day": "first"}).status_code == 422                                # 5 days cannot be a half day
    assert api.patch(co["tok"]["e6"], f"/leave/requests/{r['id']}", {"reason": "hijack"}).status_code == 404
    assert api.patch(co["tok"]["mgr"], f"/leave/requests/{r['id']}", {"reason": "hijack"}).status_code == 404
    decide(api, co, "mgr", r["id"])
    assert api.patch(tok, f"/leave/requests/{r['id']}", {"reason": "too late"}).status_code == 409
    assert api.post(tok, f"/leave/requests/{other['id']}/cancel").status_code == 200


# --------------------------------------------------------- charging, refunds and the ledger

def test_every_booking_is_in_the_ledger_and_the_ledger_reconciles(api, co):
    tid = co["types"]["Annual Leave"]["id"]
    d = monday(7)
    r = ask(api, co, "e6", start=d, end=d + timedelta(days=2)).json()
    y = d.year
    before = bal(api, co, "e6", year=y)
    assert decide(api, co, "mgr", r["id"]).status_code == 200
    after = bal(api, co, "e6", year=y)
    assert after["used"] == before["used"] + 3 and after["remaining"] == before["remaining"] - 3
    kinds = [(e["kind"], e["days"]) for e in api.get(co["tok"]["e6"], f"/leave/ledger?leave_type_id={tid}&year={y}&page_size=100").json()["items"]]
    assert ("use", -3.0) in kinds and any(k == "grant" for k, _ in kinds)
    assert decide(api, co, "mgr", r["id"]).status_code == 409                        # a second approval is refused
    assert api.post(co["tok"]["e6"], f"/leave/requests/{r['id']}/cancel").json()["status"] == "cancelled"
    assert api.post(co["tok"]["e6"], f"/leave/requests/{r['id']}/cancel").status_code == 409
    final = bal(api, co, "e6", year=y)
    assert final["remaining"] == before["remaining"] and final["used"] == before["used"]
    assert ledger_sum(api, co, "e6", tid, y) == final["remaining"]                      # remaining == the sum of all entries


def test_the_same_request_is_never_charged_twice(api, co):
    tid = co["types"]["Annual Leave"]["id"]
    d = monday(8)
    r = ask(api, co, "e7", start=d, end=d + timedelta(days=1)).json()
    y = d.year
    before = bal(api, co, "e7", year=y)
    decide(api, co, "mgr", r["id"])
    # booking the same charge again (a retried job, a replayed message) is a no-op
    with tdb() as db:
        req, lt = db.get(LeaveRequest, r["id"]), db.get(LeaveType, tid)
        svc.charge(db, req, lt, actor=None)
        svc.charge(db, req, lt, actor=None)
        assert svc.refund(db, req, None) is True
        assert svc.refund(db, req, None) is False
        db.commit()
    now = bal(api, co, "e7", year=y)
    assert now["used"] == before["used"]                                             # charged once, refunded once
    assert ledger_sum(api, co, "e7", tid, y) == now["remaining"]


def test_two_simultaneous_approvals_charge_once(api, co):
    d = monday(9)
    r = ask(api, co, "e8", start=d, end=d + timedelta(days=1)).json()
    y = d.year
    before = bal(api, co, "e8", year=y)

    def go(_):
        return decide(api, co, "mgr", r["id"]).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(go, range(2)))
    assert codes[0] == 200 and codes[1] in (409, 500) and codes.count(200) == 1, codes
    now = bal(api, co, "e8", year=y)
    assert now["used"] == before["used"] + 2, (codes, before["used"], now["used"])


def test_a_balance_cannot_be_overdrawn(api, co):
    # Casual leave: 6 days. Pending days count against what can still be requested...
    d = monday(10)
    assert ask(api, co, "e9", "Casual Leave", start=d, end=d + timedelta(days=3)).status_code == 201
    second = ask(api, co, "e9", "Casual Leave", start=monday(12), end=monday(12) + timedelta(days=3))
    assert second.status_code == 400 and second.json()["error"]["code"] == "insufficient_balance"
    # ...and the charge itself is guarded inside the UPDATE: booking more than is left fails even if the application checks were bypassed.
    with tdb() as db:
        lt = db.scalar(select(LeaveType).where(LeaveType.name == "Casual Leave"))
        u = db.scalar(select(User).where(User.email == "e9@lvco.com"))
        too_big = LeaveRequest(user_id=u.id, leave_type_id=lt.id, start_date=monday(14), end_date=monday(14) + timedelta(days=6), days=7.0, status="approved")
        db.add(too_big)
        db.flush()
        with pytest.raises(Exception, match="enough balance"):
            svc.charge(db, too_big, lt, actor=None)
        db.rollback()
    assert bal(api, co, "e9", "Casual Leave", year=monday(14).year)["used"] == 0


# --------------------------------------------------------------------------- revisions

def test_revising_approved_leave_swaps_it_atomically(api, co):
    tid = co["types"]["Casual Leave"]["id"]
    tok = co["tok"]["e10"]
    d = monday(11)
    y = d.year
    orig = ask(api, co, "e10", "Casual Leave", start=d, end=d + timedelta(days=4)).json()      # 5 of 6 days
    decide(api, co, "mgr", orig["id"])
    assert bal(api, co, "e10", "Casual Leave", year=y)["remaining"] == 1
    rev_url = f"/leave/requests/{orig['id']}/revise"
    body = {"leave_type_id": tid, "start_date": (d + timedelta(days=7)).isoformat(), "end_date": (d + timedelta(days=13)).isoformat()}   # 5 days, a week later
    assert api.post(co["tok"]["e11"], rev_url, body).status_code == 404
    rev = api.post(tok, rev_url, body)
    assert rev.status_code == 201 and rev.json()["supersedes_id"] == orig["id"] and rev.json()["status"] == "pending"
    assert api.post(tok, rev_url, body).status_code == 409                                       # one pending revision at a time
    mine = {r["id"]: r for r in api.get(tok, "/leave/requests/mine?page_size=50").json()["items"]}
    assert mine[orig["id"]]["status"] == "approved"                                              # still in force while the revision waits
    assert bal(api, co, "e10", "Casual Leave", year=y)["remaining"] == 1
    assert decide(api, co, "mgr", rev.json()["id"]).status_code == 200
    mine = {r["id"]: r for r in api.get(tok, "/leave/requests/mine?page_size=50").json()["items"]}
    assert mine[orig["id"]]["status"] == "superseded" and mine[rev.json()["id"]]["status"] == "approved"
    after = bal(api, co, "e10", "Casual Leave", year=y)
    assert after["used"] == 5 and after["remaining"] == 1                                        # charged for the new leave only
    assert ledger_sum(api, co, "e10", tid, y) == after["remaining"]
    assert api.post(tok, f"/leave/requests/{orig['id']}/cancel").status_code == 409              # a superseded request is history
    too_long = {**body, "end_date": (d + timedelta(days=20)).isoformat()}
    assert api.post(tok, f"/leave/requests/{rev.json()['id']}/revise", too_long).status_code == 400   # 6 free days exist, not 11


def test_a_rejected_revision_leaves_the_original_alone(api, co):
    tid = co["types"]["Annual Leave"]["id"]
    tok = co["tok"]["e11"]
    d = monday(13)
    orig = ask(api, co, "e11", start=d, end=d + timedelta(days=1)).json()
    decide(api, co, "mgr", orig["id"])
    y = d.year
    used = bal(api, co, "e11", year=y)["used"]
    assert used == 2
    rev = api.post(tok, f"/leave/requests/{orig['id']}/revise", {"leave_type_id": tid, "start_date": (d + timedelta(days=7)).isoformat(), "end_date": (d + timedelta(days=8)).isoformat()}).json()
    assert decide(api, co, "mgr", rev["id"], False, "no").json()["status"] == "rejected"
    mine = {r["id"]: r for r in api.get(tok, "/leave/requests/mine?page_size=50").json()["items"]}
    assert mine[orig["id"]]["status"] == "approved" and bal(api, co, "e11", year=y)["used"] == used
    assert api.post(tok, f"/leave/requests/{ask(api, co, 'e11', start=monday(30)).json()['id']}/revise",
                    {"leave_type_id": tid, "start_date": monday(31).isoformat(), "end_date": monday(31).isoformat()}).status_code == 409    # pending, not approved


# --------------------------------------------------------------------------- delegation

def test_a_delegate_can_decide_for_a_managers_team_during_the_window(api, co):
    d, tok = monday(15), co["tok"]
    r = ask(api, co, "e12", start=d).json()
    assert decide(api, co, "mgrd", r["id"]).status_code == 403                                   # no authority yet
    assert api.get(tok["mgrd"], "/leave/requests").json()["total"] == 0
    assert api.post(tok["e12"], "/leave/delegations", {"delegate_id": co["ids"]["mgrd"], "start_date": str(utcnow().date()), "end_date": str(d)}).status_code == 403
    assert api.post(tok["mgr"], "/leave/delegations", {"delegate_id": co["ids"]["e12"], "start_date": str(utcnow().date()), "end_date": str(d)}).status_code == 400   # employees can't approve
    assert api.post(tok["mgr"], "/leave/delegations", {"delegate_id": co["ids"]["mgr"], "start_date": str(utcnow().date()), "end_date": str(d)}).status_code == 400    # not yourself
    assert api.post(tok["mgr"], "/leave/delegations", {"delegate_id": co["ids"]["mgrd"], "start_date": "2020-01-01", "end_date": "2020-02-01"}).status_code == 400   # over already
    made = api.post(tok["mgr"], "/leave/delegations", {"delegate_id": co["ids"]["mgrd"], "start_date": str(utcnow().date()), "end_date": str(d)})
    assert made.status_code == 201 and made.json()["active"] is True
    assert any("delegated" in n["title"] for n in api.get(tok["mgrd"], "/notifications").json()["items"])
    new = ask(api, co, "e13", start=d + timedelta(days=21)).json()
    assert "Leave request" in [n["title"] for n in api.get(tok["mgrd"], "/notifications").json()["items"]]   # told about new requests as well
    queue = {x["id"] for x in api.get(tok["mgrd"], "/leave/requests?status=pending&page_size=100").json()["items"]}
    assert {r["id"], new["id"]} <= queue
    assert co["ids"]["b1"] not in {x["user_id"] for x in api.get(tok["mgrd"], "/leave/requests?page_size=100").json()["items"]}   # not another manager's team
    ok = decide(api, co, "mgrd", r["id"], True, "covering")
    assert ok.status_code == 200 and ok.json()["decided_via"] == co["ids"]["mgr"] and ok.json()["decided_by_name"]
    b1 = ask(api, co, "b1", start=d).json()
    assert decide(api, co, "mgrd", b1["id"]).status_code == 403                                  # someone else's team
    own = ask(api, co, "mgrd", start=d + timedelta(days=28))
    assert decide(api, co, "mgrd", own.json()["id"]).status_code == 403                          # never your own
    assert api.delete(tok["e12"], f"/leave/delegations/{made.json()['id']}").status_code == 404   # only the delegator can end it
    mine = api.get(tok["mgr"], "/leave/delegations").json()["items"]
    assert mine[0]["direction"] == "given" and api.get(tok["mgrd"], "/leave/delegations").json()["items"][0]["direction"] == "received"
    assert api.delete(tok["mgr"], f"/leave/delegations/{made.json()['id']}").status_code == 204
    assert decide(api, co, "mgrd", new["id"]).status_code == 403                                 # revoked
    assert api.get(tok["mgrd"], "/leave/requests").json()["total"] == 0
    audit = {a["action"] for a in api.get(co["f"], "/admin/audit-logs?page_size=100").json()["items"]}
    assert {"leave.delegated", "leave.delegation_revoked"} <= audit


# ------------------------------------------------------------- policy changes never rewrite history

def test_policy_changes_do_not_touch_existing_leave(api, co):
    t = co["types"]["Sick Leave"]
    d = monday(16)
    r = ask(api, co, "e14", "Sick Leave", start=d, end=d + timedelta(days=1)).json()
    decide(api, co, "mgr", r["id"])
    before = bal(api, co, "e14", "Sick Leave")
    body = {k: t[k] for k in ("name", "annual_quota", "paid", "accrual", "carry_forward_max", "allow_half_day", "count_all_days", "min_notice_days", "encashable", "is_active")}
    # holiday added inside the approved range later: the approved request keeps the days it was approved with
    assert api.post(co["f"], "/leave/holidays", {"name": "Late holiday", "date": (d + timedelta(days=1)).isoformat()}).status_code == 201
    mine = {x["id"]: x for x in api.get(co["tok"]["e14"], "/leave/requests/mine").json()["items"]}
    assert mine[r["id"]]["days"] == 2
    # quota change without the tick: nobody's current balance moves
    assert api.patch(co["f"], f"/leave/types/{t['id']}", {**body, "annual_quota": 14}).status_code == 200
    assert bal(api, co, "e14", "Sick Leave")["allocated"] == before["allocated"]
    # with the tick: everyone gets the difference as a visible adjustment, and the approved request is still 2 days
    assert api.patch(co["f"], f"/leave/types/{t['id']}", {**body, "annual_quota": 16, "apply_to_current_year": True}).status_code == 200
    after = bal(api, co, "e14", "Sick Leave")
    assert after["allocated"] == before["allocated"] + 2 and after["used"] == before["used"]
    assert any(e["kind"] == "adjust" and e["days"] == 2 for e in api.get(co["tok"]["e14"], f"/leave/ledger?leave_type_id={t['id']}").json()["items"])
    assert {x["id"]: x for x in api.get(co["tok"]["e14"], "/leave/requests/mine").json()["items"]}[r["id"]]["days"] == 2
    assert api.patch(co["tok"]["e14"], f"/leave/types/{t['id']}", body).status_code == 403
    assert api.patch(co["f"], f"/leave/types/{t['id']}", {**body, "carry_expiry_months": 3}).status_code == 422     # expiry needs a carry limit
    api.patch(co["f"], f"/leave/types/{t['id']}", {**body, "annual_quota": 10})


def test_inactive_leave_types_disappear_for_employees(api, co):
    t = api.post(co["f"], "/leave/types", {"name": "Sabbatical", "annual_quota": 3}).json()
    body = {"name": "Sabbatical", "annual_quota": 3, "is_active": False}
    api.patch(co["f"], f"/leave/types/{t['id']}", body)
    assert "Sabbatical" not in [x["name"] for x in api.get(co["tok"]["e1"], "/leave/types").json()["items"]]
    assert "Sabbatical" in [x["name"] for x in api.get(co["tok"]["hr"], "/leave/types?include_inactive=true").json()["items"]]
    assert "Sabbatical" not in [x["name"] for x in api.get(co["tok"]["e1"], "/leave/types?include_inactive=true").json()["items"]]
    r = api.post(co["tok"]["e1"], "/leave/requests", {"leave_type_id": t["id"], "start_date": monday(40).isoformat(), "end_date": monday(40).isoformat()})
    assert r.status_code == 400 and "no longer available" in r.json()["error"]["message"]


# ------------------------------------------------------------ accrual, carry-forward, expiry

def _set_hired(email, d):
    with tdb() as db:
        db.scalar(select(User).where(User.email == email)).hire_date = d
        db.commit()


def test_monthly_accrual_is_booked_once_per_month(api, co):
    t = api.post(co["f"], "/leave/types", {"name": "Earned", "annual_quota": 12, "accrual": "monthly"}).json()
    co["types"]["Earned"] = t
    today = utcnow().date()
    _set_hired("o1@lvco.com", date(today.year, 1, 1))
    b = bal(api, co, "o1", "Earned")
    assert b["allocated"] == round(12 * today.month / 12, 2)
    assert bal(api, co, "o1", "Earned")["allocated"] == b["allocated"]                           # reading again books nothing more
    rows = [e for e in api.get(co["tok"]["o1"], f"/leave/ledger?leave_type_id={t['id']}&page_size=100").json()["items"] if e["kind"] == "grant"]
    assert len(rows) == today.month and len({e["period"] for e in rows}) == today.month
    over = ask(api, co, "o1", "Earned", start=monday(4), end=monday(4) + timedelta(days=4))
    if today.month < 5:
        assert over.status_code == 400                                                           # not accrued yet
    _set_hired("e15@lvco.com", today)
    assert bal(api, co, "e15", "Earned")["allocated"] == round(12 * today.month / 12, 2) - round(12 * (today.month - 1) / 12, 2)   # only from the joining month


def test_carry_forward_and_expiry(api, co):
    t = api.post(co["f"], "/leave/types", {"name": "Carry", "annual_quota": 10, "carry_forward_max": 4, "carry_expiry_months": 3}).json()
    year = utcnow().date().year
    with tdb() as db:
        lt = db.get(LeaveType, t["id"])
        a = db.scalar(select(User).where(User.email == "e1@lvco.com"))
        b = db.scalar(select(User).where(User.email == "e2@lvco.com"))
        for u in (a, b):
            u.hire_date = date(year - 3, 1, 1)
        db.flush()
        svc.ensure_balances(db, a, year - 1)
        svc.ensure_balances(db, b, year - 1)
        svc.post_entry(db, user_id=b.id, type_id=lt.id, year=year - 1, kind="use", days=-8, note="took 8 days last year")   # 2 left over -> carries 2
        db.commit()
    with tdb() as db:
        early = svc.run_maintenance(db, date(year, 2, 10))
        db.commit()
    assert early["carried_days"] == 6 and early["expired_days"] == 0                              # a: min(10, 4) = 4, b: min(2, 4) = 2
    with tdb() as db:
        again = svc.run_maintenance(db, date(year, 2, 11))
        db.commit()
    assert again["carried_days"] == 0                                                            # idempotent
    ba = [x for x in api.get(co["tok"]["e1"], f"/leave/balances?year={year}").json()["items"] if x["leave_type"] == "Carry"][0]
    assert ba["carried_in"] == 4 and ba["remaining"] == 14
    # a takes 1 carried day in February (approved, start before the expiry), then March passes
    with tdb() as db:
        lt = db.get(LeaveType, t["id"])
        u = db.scalar(select(User).where(User.email == "e1@lvco.com"))
        req = LeaveRequest(user_id=u.id, leave_type_id=lt.id, start_date=date(year, 2, 16), end_date=date(year, 2, 16), days=1.0, status="approved")
        db.add(req)
        db.flush()
        svc.charge(db, req, lt, actor=None)
        late = svc.run_maintenance(db, date(year, 4, 1))
        again = svc.run_maintenance(db, date(year, 4, 2))
        db.commit()
    assert late["expired_days"] == 3 + 2 and again["expired_days"] == 0                           # a: 4 carried - 1 used = 3; b: 2
    ba = [x for x in api.get(co["tok"]["e1"], f"/leave/balances?year={year}").json()["items"] if x["leave_type"] == "Carry"][0]
    assert ba["expired"] == 3 and ba["remaining"] == 10 + 4 - 1 - 3
    assert ledger_sum(api, co, "e1", t["id"], year) == ba["remaining"]
    kinds = {e["kind"] for e in api.get(co["tok"]["e1"], f"/leave/ledger?leave_type_id={t['id']}&year={year}&page_size=100").json()["items"]}
    assert {"grant", "carry_in", "use", "expire"} <= kinds


def test_maintenance_endpoint(api, co):
    r = api.post(co["tok"]["hr"], "/leave/maintenance")
    assert r.status_code == 200 and set(r.json()) == {"users", "carried_days", "expired_days"}
    assert api.post(co["tok"]["hr"], "/leave/maintenance").json()["carried_days"] == 0
    assert api.post(co["tok"]["e1"], "/leave/maintenance").status_code == 403
    assert api.post(co["tok"]["mgr"], "/leave/maintenance").status_code == 403


# ------------------------------------------------------------------- adjust and encash

def test_adjustments_need_a_note_and_cannot_go_negative(api, co):
    hr, tid = co["tok"]["hr"], co["types"]["Annual Leave"]["id"]
    uid = co["ids"]["e1"]
    start = bal(api, co, "e1")["remaining"]
    assert api.post(hr, f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": 2, "note": "x"}).status_code == 422
    assert api.post(hr, f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": 0, "note": "nothing"}).status_code == 422
    assert api.post(hr, f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": -500, "note": "too much"}).status_code == 422
    assert api.post(hr, f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": -100, "note": "too much"}).status_code == 400
    ok = api.post(hr, f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": 2, "note": "Worked a public holiday"})
    assert ok.status_code == 200 and bal(api, co, "e1")["remaining"] == start + 2
    assert api.post(co["tok"]["e1"], f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": 5, "note": "give me days"}).status_code == 403
    assert api.post(co["tok"]["mgr"], f"/leave/balances/{uid}/adjust", {"leave_type_id": tid, "days": 5, "note": "managers cannot"}).status_code == 403
    assert any("adjusted" in n["title"] for n in api.get(co["tok"]["e1"], "/notifications").json()["items"])


def test_encashment_respects_the_per_year_limit(api, co):
    t = api.post(co["f"], "/leave/types", {"name": "Privilege", "annual_quota": 15, "encashable": True, "encash_max_days": 5}).json()
    uid, hr = co["ids"]["e2"], co["tok"]["hr"]
    url = f"/leave/balances/{uid}/encash"
    assert api.post(hr, url, {"leave_type_id": co["types"]["Annual Leave"]["id"], "days": 1}).status_code == 400            # not encashable
    assert api.post(hr, url, {"leave_type_id": t["id"], "days": 3, "note": "FY payout"}).status_code == 200
    b = [x for x in api.get(co["tok"]["e2"], "/leave/balances").json()["items"] if x["leave_type"] == "Privilege"][0]
    assert b["encashed"] == 3 and b["remaining"] == 12
    r = api.post(hr, url, {"leave_type_id": t["id"], "days": 3})
    assert r.status_code == 400 and r.json()["error"]["code"] == "encash_limit"
    assert api.post(hr, url, {"leave_type_id": t["id"], "days": 2}).status_code == 200
    assert api.post(co["tok"]["e2"], url, {"leave_type_id": t["id"], "days": 1}).status_code == 403
    assert ledger_sum(api, co, "e2", t["id"]) == 10


# ---------------------------------------------------------------------- scope and holidays

def test_balances_and_ledgers_respect_scope(api, co):
    t = co["tok"]
    g1, e1 = co["ids"]["g1"], co["ids"]["e1"]
    assert api.get(t["hro"], f"/leave/balances/{g1}").status_code == 404           # another branch's HR
    assert api.get(t["hrg"], f"/leave/balances/{g1}").status_code == 200
    assert api.get(t["mgrb"], f"/leave/balances/{e1}").status_code == 404          # another manager's report
    assert api.get(t["mgr"], f"/leave/balances/{e1}").status_code == 200
    assert api.get(co["f"], f"/leave/balances/{g1}").status_code == 200
    assert api.get(t["e2"], f"/leave/balances/{e1}").status_code == 403
    assert api.get(t["e2"], f"/leave/ledger?user_id={e1}").status_code == 404
    assert api.get(t["mgrb"], f"/leave/ledger?user_id={e1}").status_code == 404
    assert api.post(t["hro"], f"/leave/balances/{g1}/adjust", {"leave_type_id": co["types"]["Annual Leave"]["id"], "days": 1, "note": "other branch"}).status_code == 404


def test_holidays_on_a_day_some_branch_works_are_allowed(api, co):
    year = utcnow().date().year + 2
    sat = next(date(year, 3, d) for d in range(1, 8) if date(year, 3, d).weekday() == 5)
    sun = sat + timedelta(days=1)
    assert api.post(co["tok"]["hr"], "/leave/holidays", {"name": "Saturday", "date": sat.isoformat()}).status_code == 400
    assert api.post(co["tok"]["hr"], "/leave/holidays", {"name": "Gulf national day", "date": sun.isoformat()}).status_code == 201   # Sunday is a Gulf workday


def test_reports(api, co):
    year = utcnow().date().year
    rows = api.get(co["tok"]["mgr"], "/leave/reports/balances").json()["items"]
    assert rows and {r["employee"] for r in rows} <= {f"E{i} Test" for i in range(1, 16)} | {"Mgr Test"}      # only the manager's own scope
    assert co["ids"]["b1"] not in {r["user_id"] for r in rows}
    all_rows = api.get(co["f"], f"/leave/reports/balances?year={year}").json()["items"]
    assert {"Annual Leave", "Casual Leave"} <= {r["leave_type"] for r in all_rows} and len(all_rows) > len(rows)
    csv = api.get(co["tok"]["hr"], "/leave/reports/balances.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "Carried in" in csv.text and "Annual Leave" in csv.text
    usage = api.get(co["tok"]["hr"], f"/leave/reports/usage?year={year}").json()
    assert usage["year"] == year and "approved" in usage["statuses"] and usage["by_type"]
    assert all(len(x["months"]) == 12 for x in usage["by_type"])
    assert api.get(co["tok"]["e1"], "/leave/reports/balances").status_code == 403
    gulf = [b["id"] for b in api.get(co["f"], "/branches").json()["items"] if b["name"] == "Gulf"][0]
    gulf_rows = api.get(co["f"], f"/leave/reports/balances?branch_id={gulf}").json()["items"]
    assert gulf_rows and {r["user_id"] for r in gulf_rows} == {co["ids"]["hrg"], co["ids"]["mgrg"], co["ids"]["g1"]}


def test_other_companies_see_none_of_it(api, co):
    api.ensure_company("lvco2")
    f2 = api.login("lvco2", "founder@lvco2.com")
    assert api.get(f2, "/leave/requests?status=all&page_size=100").json()["items"] == []
    assert api.get(f2, "/leave/delegations").json()["items"] == []
    assert api.get(f2, f"/leave/balances/{co['ids']['b1']}").status_code == 404           # that id does not exist in this company
    assert api.get(f2, f"/leave/ledger?user_id={co['ids']['b1']}").status_code == 404
    other = api.get(f2, "/leave/ledger?page_size=100").json()["items"]
    assert other and all(e["kind"] == "grant" for e in other)                              # only this company's own opening grants
    rid = api.get(co["tok"]["e1"], "/leave/requests/mine").json()["items"][0]["id"]
    assert api.post(f2, f"/leave/requests/{rid}/decision", {"approved": True}).status_code == 404
    assert api.post(f2, "/leave/maintenance").json()["users"] == 1                         # runs on its own database only

