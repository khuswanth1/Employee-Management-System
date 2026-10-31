"""Performance management through the API: cycles, goals/KPIs, the self -> manager -> acknowledge workflow, confidentiality, feedback, reports."""
from datetime import date, timedelta

import pytest

from tests.conftest import PW
from app.db.base import utcnow


@pytest.fixture(scope="module")
def co(api):
    api.make_company("perfco")
    f = api.login("perfco", "founder@perfco.com")
    hr = api.add_user(f, "hr@perfco.com", "hr")
    mgr = api.add_user(f, "mgr@perfco.com", "manager")
    mgr2 = api.add_user(f, "mgr2@perfco.com", "manager")
    eng = api.post(f, "/departments", {"name": "Engineering"}).json()
    people = {n: api.add_user(f, f"{n}@perfco.com", "employee", manager_id=mgr["id"], department_id=eng["id"]) for n in ("e1", "e2", "e3", "e4")}
    people["o1"] = api.add_user(f, "o1@perfco.com", "employee", manager_id=mgr2["id"])
    people["orphan"] = api.add_user(f, "orphan@perfco.com", "employee")
    api.post(f, "/board/members", {"email": "board@perfco.com", "full_name": "Board Person", "password": PW, "designation": "Director", "permissions": ["analytics.view"]})
    names = ["hr", "mgr", "mgr2", *people]
    tok = {n: api.login("perfco", f"{n}@perfco.com") for n in names}
    tok["board"] = api.login("perfco", "board@perfco.com")
    ids = {"hr": hr["id"], "mgr": mgr["id"], "mgr2": mgr2["id"], **{n: p["id"] for n, p in people.items()}}
    return {"f": f, "tok": tok, "ids": ids}


def mk_cycle(api, co, name, activate=False, **extra):
    today = utcnow().date()
    body = {"name": name, "start_date": str(today - timedelta(days=30)), "end_date": str(today + timedelta(days=60)), "competencies": ["Quality", "Teamwork"], **extra}
    r = api.post(co["f"], "/performance/cycles", body)
    assert r.status_code == 201, r.text
    c = r.json()
    if activate:
        a = api.post(co["f"], f"/performance/cycles/{c['id']}/activate")
        assert a.status_code == 200, a.text
        c = a.json()
    return c


def my_review(api, co, who, cid):
    return api.get(co["tok"][who], f"/performance/reviews/mine?cycle_id={cid}").json()["items"][0]


def finish_self(api, co, who, cid, rating=4):
    rv = my_review(api, co, who, cid)
    t = co["tok"][who]
    assert api.put(t, f"/performance/reviews/{rv['id']}/self", {"rating": rating, "comments": "I delivered on my objectives.", "competencies": {"Quality": rating, "Teamwork": rating}}).status_code == 200
    r = api.post(t, f"/performance/reviews/{rv['id']}/self/submit")
    assert r.status_code == 200, r.text
    return rv["id"]


def finish_manager(api, co, mgr, rid, rating=3, comments="Solid year with room to grow.", goals=None):
    t = co["tok"][mgr]
    body = {"rating": rating, "comments": comments, "strengths": "Reliable", "development_areas": "Delegation", "competencies": {"Quality": rating, "Teamwork": rating}, "goals": goals or {}}
    assert api.put(t, f"/performance/reviews/{rid}/manager", body).status_code == 200
    return api.post(t, f"/performance/reviews/{rid}/manager/submit")


# ----------------------------------------------------------------------------- scales & cycles

def test_rating_scales_and_cycle_setup(api, co):
    f, hr = co["f"], co["tok"]["hr"]
    default = api.get(co["tok"]["e1"], "/performance/scales").json()["items"]
    assert [lv["value"] for lv in default[0]["levels"]] == [1, 2, 3, 4, 5]
    assert api.post(co["tok"]["e1"], "/performance/scales", {"name": "x1", "levels": []}).status_code == 403
    assert api.post(hr, "/performance/scales", {"name": "Bad", "levels": [{"value": 1, "label": "a"}, {"value": 1, "label": "b"}]}).status_code == 422
    assert api.post(hr, "/performance/scales", {"name": "Bad2", "levels": [{"value": 1, "label": "only"}]}).status_code == 422
    three = api.post(hr, "/performance/scales", {"name": "Three", "levels": [{"value": 3, "label": "High"}, {"value": 1, "label": "Low"}, {"value": 2, "label": "Mid"}]})
    assert three.status_code == 201 and [lv["value"] for lv in three.json()["levels"]] == [1, 2, 3]
    assert api.post(hr, "/performance/scales", {"name": "three", "levels": [{"value": 1, "label": "a"}, {"value": 2, "label": "b"}]}).status_code == 409

    today = utcnow().date()
    ok = {"name": "H1 setup", "start_date": str(today), "end_date": str(today + timedelta(days=90))}
    assert api.post(co["tok"]["mgr"], "/performance/cycles", ok).status_code == 403
    assert api.post(hr, "/performance/cycles", {**ok, "end_date": str(today)}).status_code == 422
    assert api.post(hr, "/performance/cycles", {**ok, "self_review_due": str(today + timedelta(days=30)), "manager_review_due": str(today + timedelta(days=10))}).status_code == 422
    assert api.post(hr, "/performance/cycles", {**ok, "competencies": ["Quality", "quality"]}).status_code == 422
    made = api.post(hr, "/performance/cycles", {**ok, "scale_id": three.json()["id"], "competencies": ["Quality"]})
    assert made.status_code == 201 and made.json()["status"] == "draft" and made.json()["scale"]["name"] == "Three"
    assert api.post(hr, "/performance/cycles", ok).status_code == 409                                  # names are unique
    cid = made.json()["id"]
    assert api.get(co["tok"]["e1"], "/performance/cycles").json()["items"] == []                       # drafts are invisible to staff only
    assert api.patch(hr, f"/performance/cycles/{cid}", {**ok, "competencies": ["Quality", "Speed"]}).json()["competencies"] == ["Quality", "Speed"]
    assert api.delete(hr, f"/performance/cycles/{cid}").status_code == 204


def test_activation_opens_a_review_per_eligible_person_only(api, co):
    c = mk_cycle(api, co, "Activation", activate=True)
    assert c["status"] == "active"
    n = c["review_counts"]["pending_self"]
    assert n == 9                                                                                         # hr, 2 managers, 6 employees; not the founder, not the board member
    assert api.post(co["f"], f"/performance/cycles/{c['id']}/activate").status_code == 409
    for who in ("e1", "mgr", "hr"):
        assert my_review(api, co, who, c["id"])["status"] == "pending_self"
    assert api.get(co["tok"]["board"], f"/performance/reviews/mine?cycle_id={c['id']}").json()["items"] == []
    assert api.get(co["f"], f"/performance/reviews/mine?cycle_id={c['id']}").json()["items"] == []
    assert any("review started" in x["title"].lower() for x in api.get(co["tok"]["e1"], "/notifications").json()["items"])
    assert api.patch(co["f"], f"/performance/cycles/{c['id']}", {"name": "Activation", "start_date": c["start_date"], "end_date": c["end_date"], "competencies": ["Other"]}).status_code == 409
    assert api.delete(co["f"], f"/performance/cycles/{c['id']}").status_code == 409
    assert [x["id"] for x in api.get(co["tok"]["e1"], "/performance/cycles").json()["items"]] == [c["id"]]
    co["act"] = c["id"]


# ---------------------------------------------------------------------------------- goals

def test_goals_proposed_by_the_employee_wait_for_the_manager(api, co):
    cid, e1, mgr = co["act"], co["tok"]["e1"], co["tok"]["mgr"]
    uid = co["ids"]["e1"]
    g = api.post(e1, "/performance/goals", {"cycle_id": cid, "title": "Ship the portal", "weight": 60, "due_date": str(utcnow().date() + timedelta(days=30))})
    assert g.status_code == 201 and g.json()["status"] == "proposed"
    assert api.post(e1, f"/performance/goals/{g.json()['id']}/updates", {"progress": 10}).status_code == 409           # not agreed yet
    assert api.post(e1, f"/performance/goals/{g.json()['id']}/agree").status_code == 403                                 # not your own
    assert api.post(co["tok"]["mgr2"], f"/performance/goals/{g.json()['id']}/agree").status_code == 404                 # not their team
    assert api.post(co["tok"]["e2"], f"/performance/goals/{g.json()['id']}/agree").status_code == 404
    agreed = api.post(mgr, f"/performance/goals/{g.json()['id']}/agree")
    assert agreed.json()["status"] == "agreed" and agreed.json()["agreed_by"]
    assert api.post(mgr, f"/performance/goals/{g.json()['id']}/agree").status_code == 409
    assert any("Goal agreed" in n["title"] for n in api.get(e1, "/notifications").json()["items"])
    over = api.post(e1, "/performance/goals", {"cycle_id": cid, "title": "Too much", "weight": 50})
    assert over.status_code == 400 and over.json()["error"]["code"] == "weight_exceeded"                                 # 60 + 50 > 100
    assert api.post(e1, "/performance/goals", {"cycle_id": cid, "title": "Fits", "weight": 40}).status_code == 201
    listing = api.get(e1, f"/performance/goals?cycle_id={cid}").json()
    assert listing["total_weight"] == 100 and len(listing["items"]) == 2
    # an agreed goal is the manager's to change
    assert api.patch(e1, f"/performance/goals/{g.json()['id']}", {"weight": 10}).status_code == 403
    assert api.patch(mgr, f"/performance/goals/{g.json()['id']}", {"weight": 50}).json()["weight"] == 50
    # goals a manager sets are agreed at once and the person is told
    set_by_mgr = api.post(mgr, "/performance/goals", {"cycle_id": cid, "user_id": uid, "title": "Mentor a junior", "weight": 10})
    assert set_by_mgr.json()["status"] == "agreed" and any("New goal" in n["title"] for n in api.get(e1, "/notifications").json()["items"])
    assert api.post(e1, "/performance/goals", {"cycle_id": cid, "user_id": co["ids"]["e2"], "title": "For someone else"}).status_code == 404
    assert api.get(co["tok"]["e2"], f"/performance/goals?cycle_id={cid}&user_id={uid}").status_code == 404              # colleagues cannot read them
    assert api.get(co["tok"]["mgr2"], f"/performance/goals?cycle_id={cid}&user_id={uid}").status_code == 404
    assert api.get(co["tok"]["hr"], f"/performance/goals?cycle_id={cid}&user_id={uid}").status_code == 200
    assert api.get(co["tok"]["board"], f"/performance/goals?cycle_id={cid}&user_id={uid}").status_code == 404
    assert api.get(co["tok"]["board"], f"/performance/goals?cycle_id={cid}").json()["items"] == []                          # the board has no goals of its own
    co["goal"] = g.json()["id"]


def test_withdraw_and_cancel_rules(api, co):
    cid, e2, mgr = co["act"], co["tok"]["e2"], co["tok"]["mgr"]
    mine = api.post(e2, "/performance/goals", {"cycle_id": cid, "title": "Maybe later", "weight": 20}).json()
    assert api.delete(e2, f"/performance/goals/{mine['id']}").status_code == 204                          # withdraw your own unagreed proposal
    kept = api.post(e2, "/performance/goals", {"cycle_id": cid, "title": "Keep this one", "weight": 20}).json()
    api.post(mgr, f"/performance/goals/{kept['id']}/agree")
    assert api.delete(e2, f"/performance/goals/{kept['id']}").status_code == 403                          # an agreed goal is the manager's call
    assert api.delete(mgr, f"/performance/goals/{kept['id']}").status_code == 204
    left = api.get(e2, f"/performance/goals?cycle_id={cid}").json()
    assert left["total_weight"] == 0                                                                       # cancelled goals free their weight
    assert api.post(e2, "/performance/goals", {"cycle_id": cid, "title": "ok", "weight": 5}).status_code == 422   # title too short
    assert api.post(e2, "/performance/goals", {"cycle_id": cid, "title": "A KPI without a target", "kind": "kpi"}).status_code == 422
    assert api.post(e2, "/performance/goals", {"cycle_id": 9999, "title": "No such cycle"}).status_code == 404


def test_a_person_without_a_manager_has_goals_agreed_automatically(api, co):
    g = api.post(co["tok"]["orphan"], "/performance/goals", {"cycle_id": co["act"], "title": "Self directed", "weight": 100})
    assert g.status_code == 201 and g.json()["status"] == "agreed"


def test_kpi_progress_and_check_ins(api, co):
    cid, e3, mgr = co["act"], co["tok"]["e3"], co["tok"]["mgr"]
    k = api.post(e3, "/performance/goals", {"cycle_id": cid, "title": "Close 40 support tickets", "kind": "kpi", "target_value": 40, "unit": "tickets", "weight": 50}).json()
    api.post(mgr, f"/performance/goals/{k['id']}/agree")
    assert api.post(e3, f"/performance/goals/{k['id']}/updates", {"progress": 50}).status_code == 422             # a KPI is updated with a value
    u = api.post(e3, f"/performance/goals/{k['id']}/updates", {"current_value": 10, "comment": "good start"})
    assert u.status_code == 201 and u.json()["progress"] == 25 and u.json()["current_value"] == 10
    assert api.post(mgr, f"/performance/goals/{k['id']}/updates", {"current_value": 60}).json()["progress"] == 100  # clamped
    plain = api.post(e3, "/performance/goals", {"cycle_id": cid, "title": "Write the handbook", "weight": 50}).json()
    api.post(mgr, f"/performance/goals/{plain['id']}/agree")
    assert api.post(e3, f"/performance/goals/{plain['id']}/updates", {"current_value": 3}).status_code == 422
    assert api.post(e3, f"/performance/goals/{plain['id']}/updates", {"progress": 101}).status_code == 422
    assert api.post(e3, f"/performance/goals/{plain['id']}/updates", {"progress": 40, "comment": "outline done"}).json()["progress"] == 40
    assert api.post(co["tok"]["e4"], f"/performance/goals/{plain['id']}/updates", {"progress": 90}).status_code == 404
    hist = api.get(mgr, f"/performance/goals/{plain['id']}/updates").json()["items"]
    assert hist[0]["comment"] == "outline done" and hist[0]["author"]
    assert api.get(co["tok"]["e4"], f"/performance/goals/{plain['id']}/updates").status_code == 404
    co["e3_goals"] = (k["id"], plain["id"])


# ------------------------------------------------------------------------------ the workflow

def test_self_review_validation_and_privacy_of_drafts(api, co):
    cid, e4, mgr = co["act"], co["tok"]["e4"], co["tok"]["mgr"]
    rv = my_review(api, co, "e4", cid)
    url = f"/performance/reviews/{rv['id']}"
    assert api.put(e4, url + "/self", {"rating": 9}).status_code == 422                                 # not on the scale
    assert api.put(e4, url + "/self", {"competencies": {"Nonsense": 3}}).status_code == 422             # not on the form
    assert api.put(e4, url + "/self", {"goals": {"12345": 3}}).status_code == 422                       # not one of my agreed goals
    assert api.post(e4, url + "/self/submit").status_code == 400                                          # incomplete
    assert api.put(mgr, url + "/self", {"rating": 3}).status_code == 403                                  # nobody writes it for you
    assert api.put(e4, url + "/self", {"rating": 5, "comments": "Draft thoughts about my year"}).status_code == 200
    seen = api.get(mgr, url).json()
    assert seen["self_rating"] is None and seen["self_comments"] is None                                  # a draft is private
    assert api.get(e4, url).json()["self_comments"].startswith("Draft")
    assert api.put(mgr, url + "/manager", {"rating": 3, "comments": "pre-filled before the self review"}).status_code == 409   # opens only after the self review
    assert api.post(e4, url + "/self/submit").status_code == 400                                          # competencies still unrated
    assert api.put(e4, url + "/self", {"competencies": {"Quality": 5, "Teamwork": 4}}).status_code == 200
    assert api.post(e4, url + "/self/submit").json()["status"] == "pending_manager"
    assert api.put(e4, url + "/self", {"rating": 1}).status_code == 409                                   # locked after submitting
    assert api.get(mgr, url).json()["self_rating"] == 5
    assert any("Self review submitted" in n["title"] for n in api.get(mgr, "/notifications").json()["items"])


def test_full_cycle_for_one_person_with_confidentiality(api, co):
    cid, e3, mgr, hr = co["act"], co["tok"]["e3"], co["tok"]["mgr"], co["tok"]["hr"]
    kpi, plain = co["e3_goals"]
    rid = finish_self(api, co, "e3", cid, rating=5)
    url = f"/performance/reviews/{rid}"
    assert api.put(co["tok"]["mgr2"], url + "/manager", {"rating": 1}).status_code == 404                # another team's manager cannot even see it
    assert api.put(co["tok"]["e1"], url + "/manager", {"rating": 1}).status_code == 404
    assert api.put(hr, url + "/manager", {"rating": 1, "comments": "HR cannot while a reviewer exists"}).status_code == 403
    assert api.put(mgr, url + "/manager", {"rating": 3, "comments": "x", "goals": {"999": 3}}).status_code == 422
    assert api.put(mgr, url + "/manager", {"rating": 6}).status_code == 422
    assert api.post(mgr, url + "/manager/submit").status_code == 400                                       # nothing written yet
    # the manager's draft is invisible to the employee; submitting is what shares it
    api.put(mgr, url + "/manager", {"rating": 4, "comments": "Strong delivery all year.", "strengths": "Ownership", "development_areas": "Estimation",
                                    "competencies": {"Quality": 4, "Teamwork": 5}, "goals": {str(kpi): 5, str(plain): 3}})
    hidden = api.get(e3, url).json()
    assert hidden["manager_rating"] is None and hidden["manager_comments"] is None and hidden["strengths"] is None and hidden["manager_goals"] == {}
    assert api.get(e3, f"/performance/history/{co['ids']['e3']}").json()["items"][0]["manager_rating"] is None
    done = api.post(mgr, url + "/manager/submit").json()
    assert done["status"] == "completed" and done["manager_rating"] == 4
    assert done["goal_score"] == 4.0                                                                       # (50 x 5 + 50 x 3) / 100
    assert api.post(mgr, url + "/manager/submit").status_code == 409
    assert api.put(mgr, url + "/manager", {"rating": 1}).status_code == 409
    shown = api.get(e3, url).json()
    assert shown["manager_rating"] == 4 and shown["strengths"] == "Ownership" and shown["manager_competencies"] == {"Quality": 4, "Teamwork": 5} and shown["manager_goals"][str(kpi)] == 5
    assert any("review is ready" in n["title"] for n in api.get(e3, "/notifications").json()["items"])
    assert api.post(mgr, url + "/acknowledge", {}).status_code == 403                                      # only the person reviewed
    ack = api.post(e3, url + "/acknowledge", {"response": "Thank you, I agree."})
    assert ack.json()["status"] == "acknowledged" and ack.json()["employee_response"] == "Thank you, I agree."
    assert api.post(e3, url + "/acknowledge", {}).status_code == 409
    assert any("acknowledged" in n["title"].lower() for n in api.get(mgr, "/notifications").json()["items"])
    h = api.get(hr, f"/performance/history/{co['ids']['e3']}").json()["items"]
    assert h[0]["manager_rating"] == 4 and h[0]["status"] == "acknowledged"
    with_audit = {a["action"] for a in api.get(co["f"], "/admin/audit-logs?page_size=100").json()["items"]}
    assert {"performance.self_review_submitted", "performance.manager_review_submitted", "performance.review_acknowledged", "performance.history_viewed"} <= with_audit


def test_no_one_else_can_read_a_review_or_history(api, co):
    rv = my_review(api, co, "e3", co["act"])
    for who in ("e1", "e2", "mgr2", "o1", "board"):
        assert api.get(co["tok"][who], f"/performance/reviews/{rv['id']}").status_code == 404, who
        assert api.get(co["tok"][who], f"/performance/history/{co['ids']['e3']}").status_code == 404, who
    assert api.get(co["tok"]["e1"], f"/performance/reviews?cycle_id={co['act']}").status_code == 403
    mine = api.get(co["tok"]["mgr"], f"/performance/reviews?cycle_id={co['act']}&page_size=50").json()["items"]
    assert {r["user_id"] for r in mine} == {co["ids"][n] for n in ("e1", "e2", "e3", "e4")}
    everyone = api.get(co["f"], f"/performance/reviews?cycle_id={co['act']}&page_size=50").json()
    assert everyone["total"] == 9


def test_a_review_without_a_reviewer_is_written_by_hr_and_can_be_reassigned(api, co):
    cid, hr, f = co["act"], co["tok"]["hr"], co["f"]
    rid = finish_self(api, co, "orphan", cid, rating=3)
    url = f"/performance/reviews/{rid}"
    assert api.put(co["tok"]["mgr"], url + "/manager", {"rating": 3}).status_code == 404
    bad = api.post(hr, url + "/reassign", {"reviewer_id": co["ids"]["orphan"]})
    assert bad.status_code == 400                                                                          # not the person themselves
    assert api.post(hr, url + "/reassign", {"reviewer_id": co["ids"]["e1"]}).status_code == 400            # an employee cannot review
    assert api.post(co["tok"]["mgr"], url + "/reassign", {"reviewer_id": co["ids"]["mgr"]}).status_code == 403
    r = finish_manager(api, co, "hr", rid, rating=4, comments="Self-directed and dependable.")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    # reassignment for a person whose review is still open
    rid2 = my_review(api, co, "o1", cid)["id"]
    finish_self(api, co, "o1", cid, rating=3)
    moved = api.post(hr, f"/performance/reviews/{rid2}/reassign", {"reviewer_id": co["ids"]["mgr"]})
    assert moved.json()["reviewer_id"] == co["ids"]["mgr"]
    assert api.put(co["tok"]["mgr2"], f"/performance/reviews/{rid2}/manager", {"rating": 3, "comments": "not mine to write"}).status_code == 403   # the old reviewer no longer can
    assert finish_manager(api, co, "mgr", rid2, rating=3).status_code == 200
    assert api.post(hr, f"/performance/reviews/{rid2}/reassign", {"reviewer_id": co["ids"]["mgr2"]}).status_code == 409   # done: no more changes


# ------------------------------------------------------------------------------ reports, reminders, closing

def test_reminders_and_summary_reports(api, co):
    cid, f, hr = co["act"], co["f"], co["tok"]["hr"]
    assert api.post(co["tok"]["e1"], f"/performance/cycles/{cid}/remind").status_code == 403
    r = api.post(hr, f"/performance/cycles/{cid}/remind").json()
    assert r["employees"] >= 3 and r["managers"] >= 1
    assert any("reminder" in n["title"].lower() for n in api.get(co["tok"]["e1"], "/notifications").json()["items"])
    s = api.get(f, f"/performance/cycles/{cid}/summary").json()
    assert s["participants"] == 9 and s["completion"]["manager_submitted"] == 3 and s["completion"]["acknowledged"] == 1
    assert s["completion"]["self_submitted"] >= 4
    assert s["average_manager"] == round((4 + 4 + 3) / 3, 2)
    dist = {d["value"]: d["count"] for d in s["distribution"]}
    assert dist == {1: 0, 2: 0, 3: 1, 4: 2, 5: 0} 
    assert s["distribution"][3]["label"] == "Exceeds expectations"
    assert s["goals"]["count"] >= 4 and s["goals"]["completed"] >= 1
    assert s["by_department"] and s["by_department"][0]["reviews"] >= 1
    team = api.get(co["tok"]["mgr"], f"/performance/cycles/{cid}/summary").json()
    assert team["participants"] == 5 and team["completion"]["manager_submitted"] == 2                      # their 4 reports plus the one they were asked to review
    assert api.get(co["tok"]["e1"], f"/performance/cycles/{cid}/summary").status_code == 403
    assert api.get(co["tok"]["board"], f"/performance/cycles/{cid}/summary").status_code == 403
    csv = api.get(hr, f"/performance/cycles/{cid}/export.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "Manager rating" in csv.text and "e3" not in csv.text.lower().split("\n")[0]
    assert api.get(co["tok"]["mgr"], f"/performance/cycles/{cid}/export.csv").status_code == 403


def test_closing_a_cycle_freezes_everything(api, co):
    cid, f = co["act"], co["f"]
    rid = my_review(api, co, "e1", cid)["id"]
    assert api.post(co["tok"]["mgr"], f"/performance/cycles/{cid}/close").status_code == 403
    closed = api.post(f, f"/performance/cycles/{cid}/close")
    assert closed.json()["status"] == "closed"
    assert api.post(f, f"/performance/cycles/{cid}/close").status_code == 409
    assert api.put(co["tok"]["e1"], f"/performance/reviews/{rid}/self", {"rating": 3}).status_code == 409
    assert api.post(co["tok"]["e1"], "/performance/goals", {"cycle_id": cid, "title": "Too late for this cycle"}).status_code == 409
    assert api.post(co["tok"]["mgr"], f"/performance/goals/{co['goal']}/agree").status_code == 409
    assert api.post(f, f"/performance/cycles/{cid}/remind").status_code == 409
    assert api.get(co["tok"]["e3"], f"/performance/reviews/{my_review(api, co, 'e3', cid)['id']}").json()["manager_rating"] == 4   # still readable


# ----------------------------------------------------------------------------------- feedback

def test_feedback_is_visible_to_the_right_people(api, co):
    e1, e2, mgr, hr = co["tok"]["e1"], co["tok"]["e2"], co["tok"]["mgr"], co["tok"]["hr"]
    to = co["ids"]["e2"]
    assert api.post(e1, "/performance/feedback", {"to_user_id": co["ids"]["e1"], "body": "I am great"}).status_code == 400          # not yourself
    assert api.post(e1, "/performance/feedback", {"to_user_id": 999999, "body": "Hello there"}).status_code == 400
    assert api.post(e1, "/performance/feedback", {"to_user_id": to, "body": "hi"}).status_code == 422
    assert api.post(co["tok"]["board"], "/performance/feedback", {"to_user_id": to, "body": "From the board"}).status_code == 403
    shared = api.post(e1, "/performance/feedback", {"to_user_id": to, "body": "Great help on the release.", "kind": "praise"})
    private = api.post(e1, "/performance/feedback", {"to_user_id": to, "body": "Please document your changes more.", "kind": "constructive", "shared": False})
    assert shared.status_code == private.status_code == 201
    got = api.get(e2, "/performance/feedback/received").json()["items"]
    assert [x["body"] for x in got] == ["Great help on the release."]                                         # the unshared one is not shown to its subject
    assert {x["body"] for x in api.get(e1, "/performance/feedback/given").json()["items"]} >= {"Great help on the release.", "Please document your changes more."}
    about = {x["body"] for x in api.get(mgr, f"/performance/feedback/about/{to}").json()["items"]}
    assert "Please document your changes more." in about                                                       # the manager sees all of it
    assert api.get(hr, f"/performance/feedback/about/{to}").status_code == 200
    assert api.get(co["tok"]["mgr2"], f"/performance/feedback/about/{to}").status_code == 404
    assert api.get(e2, f"/performance/feedback/about/{to}").status_code == 403
    assert api.get(e1, f"/performance/feedback/about/{to}").status_code == 403
    assert any("received feedback" in n["title"] for n in api.get(e2, "/notifications").json()["items"])


# ----------------------------------------------------------------------------------- isolation

def test_other_companies_see_nothing(api, co):
    api.ensure_company("perfco2")
    f2 = api.login("perfco2", "founder@perfco2.com")
    assert api.get(f2, "/performance/cycles").json()["items"] == []
    assert api.get(f2, f"/performance/cycles/{co['act']}/summary").status_code == 404
    assert api.get(f2, f"/performance/reviews/{my_review(api, co, 'e1', co['act'])['id']}").status_code == 404
    assert api.get(f2, f"/performance/goals?cycle_id={co['act']}").status_code == 200 and api.get(f2, f"/performance/goals?cycle_id={co['act']}").json()["items"] == []
    assert api.post(f2, f"/performance/cycles/{co['act']}/close").status_code == 404
