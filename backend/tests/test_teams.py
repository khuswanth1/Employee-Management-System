"""Team management & project allocation (company 'teamco' + a second company for tenant isolation)."""
from datetime import date, timedelta

import pytest
from app.db.base import utcnow


@pytest.fixture(scope="module")
def co(api):
    api.make_company("teamco")
    f = api.login("teamco", "founder@teamco.com")
    north = api.post(f, "/branches", {"name": "North", "code": "NRT", "city": "Oslo"}).json()
    south = api.post(f, "/branches", {"name": "South", "code": "STH", "city": "Rome"}).json()
    u = {}
    for key, role, br in [
        ("mgr", "manager", north), ("mgr2", "manager", north), ("mgr_s", "manager", south), ("hr_n", "hr", north), ("hr_all", "hr", None),
        ("lead", "employee", north), ("a", "employee", north), ("b", "employee", north), ("c", "employee", north),
        ("lead2", "employee", north), ("s1", "employee", south), ("free", "employee", None),
    ]:
        u[key] = api.add_user(f, f"{key}@teamco.com", role, **({"branch_id": br["id"]} if br else {}))
    t = {k: api.login("teamco", f"{k}@teamco.com") for k in u}
    t["f"] = f
    return {"f": f, "north": north, "south": south, "u": u, "t": t}


def ids(co, *keys):
    return [co["u"][k]["id"] for k in keys]


def make_team(api, co, name, who="mgr", members=("a", "b"), leader="lead", **extra):
    body = {"name": name, "member_ids": ids(co, *members), "leader_id": co["u"][leader]["id"] if leader else None, **extra}
    r = api.post(co["t"][who], "/teams", body)
    assert r.status_code == 201, r.text
    return r.json()


def project(api, co, who="mgr", name="Proj"):
    r = api.post(co["t"][who], "/projects", {"name": name})
    assert r.status_code == 201, r.text
    return r.json()


# ---- creation, permissions, branch rules ---------------------------------------------------------------

def test_manager_creates_team_with_leader_members_and_projects(api, co):
    p = project(api, co, name="Website")
    team = make_team(api, co, "Alpha", project_ids=[p["id"]])
    assert team["manager_id"] == co["u"]["mgr"]["id"] and team["leader_id"] == co["u"]["lead"]["id"]
    assert team["branch_id"] == co["north"]["id"]  # a branch manager's team is always in their branch
    assert {m["id"] for m in team["members"]} == set(ids(co, "a", "b", "lead")) and team["member_count"] == 3
    assert [x["id"] for x in team["projects"]] == [p["id"]]
    assert next(m for m in team["members"] if m["id"] == co["u"]["lead"]["id"])["is_leader"] is True
    assert team["can_manage"] and team["can_monitor"]
    # members and the leader can see the project through the existing project machinery
    for k in ("a", "lead"):
        assert any(x["id"] == p["id"] for x in api.get(co["t"][k], "/projects").json()["items"])
    assert not any(x["id"] == p["id"] for x in api.get(co["t"]["c"], "/projects").json()["items"])
    # audit trail
    logs = api.get(co["f"], "/admin/audit-logs?action=team.created").json()["items"]
    assert any(a["entity_id"] == team["id"] and a["detail"]["leader_id"] == co["u"]["lead"]["id"] for a in logs)
    # duplicate name (case-insensitive)
    assert api.post(co["t"]["mgr"], "/teams", {"name": "alpha"}).status_code == 409


def test_only_founders_and_permitted_managers_create_teams(api, co):
    for who in ("hr_n", "a", "lead"):
        assert api.post(co["t"][who], "/teams", {"name": f"Nope {who}"}).status_code == 403
    f = co["f"]
    api.patch(f, f"/managers/{co['u']['mgr2']['id']}", {"permissions": ["projects.manage"]})
    assert api.post(co["t"]["mgr2"], "/teams", {"name": "No perm"}).status_code == 403
    api.patch(f, f"/managers/{co['u']['mgr2']['id']}", {"permissions": None})
    r = api.post(f, "/teams", {"name": "Founder Team", "manager_id": co["u"]["mgr"]["id"], "branch_id": co["north"]["id"]})
    assert r.status_code == 201 and r.json()["manager_id"] == co["u"]["mgr"]["id"]
    # the manager must be an actual manager of that branch
    assert api.post(f, "/teams", {"name": "Bad mgr", "manager_id": co["u"]["a"]["id"]}).status_code == 400
    assert api.post(f, "/teams", {"name": "Wrong branch", "branch_id": co["north"]["id"], "manager_id": co["u"]["mgr_s"]["id"]}).status_code == 400


def test_branch_and_eligibility_rules(api, co):
    t = co["t"]
    # a north manager cannot pull in people from another branch, or branchless people
    assert api.post(t["mgr"], "/teams", {"name": "X1", "member_ids": ids(co, "s1")}).status_code == 400
    assert api.post(t["mgr"], "/teams", {"name": "X2", "member_ids": ids(co, "free")}).status_code == 400
    # founders / board members / unknown people are not eligible, and leaders must be employees or managers
    fid = api.get(co["f"], "/auth/me").json()["id"]
    assert api.post(t["mgr"], "/teams", {"name": "X3", "member_ids": [fid]}).status_code == 400
    assert api.post(t["mgr"], "/teams", {"name": "X4", "member_ids": [999999]}).status_code == 400
    assert api.post(t["mgr"], "/teams", {"name": "X5", "leader_id": co["u"]["hr_n"]["id"]}).status_code == 400
    assert api.post(t["mgr"], "/teams", {"name": "X6", "project_ids": [999999]}).status_code == 404


def test_one_team_per_person_and_member_management(api, co):
    t = co["t"]
    team = make_team(api, co, "Bravo", who="mgr2", members=("c",), leader="lead2")
    other = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    # 'a' already sits in Alpha
    r = api.post(t["mgr2"], f"/teams/{team['id']}/members", {"user_ids": ids(co, "a")})
    assert r.status_code == 409 and "already in team Alpha" in r.json()["error"]["message"]
    # another manager cannot touch Alpha at all (out of scope looks non-existent)
    assert api.get(t["mgr2"], f"/teams/{other['id']}").status_code == 404
    assert api.post(t["mgr2"], f"/teams/{other['id']}/members", {"user_ids": ids(co, "free")}).status_code == 404
    # HR in the branch can add and remove members; plain members and leaders cannot
    assert api.post(t["a"], f"/teams/{other['id']}/members", {"user_ids": ids(co, "free")}).status_code == 403
    # the leader may manage members, but the same branch rule applies (this person has no branch yet)
    assert api.post(t["lead"], f"/teams/{other['id']}/members", {"user_ids": ids(co, "free")}).status_code == 400
    # 'free' has no branch -> not eligible for a branch team; give them one first
    api.post(co["f"], f"/branches/{co['north']['id']}/members", {"user_ids": ids(co, "free")})
    r = api.post(t["hr_n"], f"/teams/{other['id']}/members", {"user_ids": ids(co, "free")})
    assert r.status_code == 200 and co["u"]["free"]["id"] in {m["id"] for m in r.json()["members"]}
    r = api.delete(t["hr_n"], f"/teams/{other['id']}/members/{co['u']['free']['id']}")
    assert r.status_code == 200 and co["u"]["free"]["id"] not in {m["id"] for m in r.json()["members"]}
    assert api.delete(t["hr_n"], f"/teams/{other['id']}/members/{co['u']['free']['id']}").status_code == 404
    # HR of another branch (south) cannot see north teams; company-wide HR can
    co_south_hr = api.add_user(co["f"], "hr_s@teamco.com", "hr", branch_id=co["south"]["id"])
    assert co_south_hr["branch_id"] == co["south"]["id"]
    assert api.get(api.login("teamco", "hr_s@teamco.com"), f"/teams/{other['id']}").status_code == 404
    assert api.get(t["hr_all"], f"/teams/{other['id']}").status_code == 200


# ---- leader assignment ------------------------------------------------------------------------------

def test_assign_replace_and_clear_leader(api, co):
    t = co["t"]
    team = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    tid = team["id"]
    # a plain member and the leader themselves cannot change leadership
    assert api.put(t["a"], f"/teams/{tid}/leader", {"user_id": co["u"]["a"]["id"]}).status_code == 403
    assert api.put(t["lead"], f"/teams/{tid}/leader", {"user_id": co["u"]["lead"]["id"]}).status_code == 403
    r = api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": co["u"]["a"]["id"]})
    assert r.status_code == 200 and r.json()["leader_id"] == co["u"]["a"]["id"]
    # old leader stays a member; new leader notified
    assert co["u"]["lead"]["id"] in {m["id"] for m in r.json()["members"]}
    titles = [n["title"] for n in api.get(t["a"], "/notifications").json()["items"]]
    assert "You lead a team" in titles
    # HR cannot be a leader; someone from another team cannot be pulled in silently
    assert api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": co["u"]["hr_n"]["id"]}).status_code == 400
    assert api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": co["u"]["lead2"]["id"]}).status_code == 409
    # put the original leader back, then clear
    assert api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": co["u"]["lead"]["id"]}).json()["leader_id"] == co["u"]["lead"]["id"]
    assert api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": None}).json()["leader_id"] is None
    assert api.put(t["mgr"], f"/teams/{tid}/leader", {"user_id": co["u"]["lead"]["id"]}).status_code == 200
    acts = api.get(co["f"], "/admin/audit-logs?action=team.leader_changed&page_size=50").json()["items"]
    assert len([a for a in acts if a["entity_id"] == tid]) >= 4


# ---- project allocation + task distribution ----------------------------------------------------------

def test_project_allocation_and_leader_task_distribution(api, co):
    t, u = co["t"], co["u"]
    team = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    tid = team["id"]
    proj = project(api, co, name="Mobile app")
    # not the owner of the project -> cannot allocate it
    other_proj = project(api, co, who="mgr2", name="Other mgr project")
    assert api.post(t["mgr"], f"/teams/{tid}/projects", {"project_id": other_proj["id"]}).status_code in (403, 404)
    assert api.post(t["lead"], f"/teams/{tid}/projects", {"project_id": proj["id"]}).status_code == 403
    r = api.post(t["mgr"], f"/teams/{tid}/projects", {"project_id": proj["id"]})
    assert r.status_code == 201 and proj["id"] in [p["id"] for p in r.json()["projects"]]
    assert api.post(t["mgr"], f"/teams/{tid}/projects", {"project_id": proj["id"]}).status_code == 409
    # members now see it; outsiders still don't
    assert any(x["id"] == proj["id"] for x in api.get(t["b"], "/projects").json()["items"])
    assert not any(x["id"] == proj["id"] for x in api.get(t["c"], "/projects").json()["items"])
    due = (utcnow().date() + timedelta(days=5)).isoformat()
    # a plain member cannot create tasks; the leader can - for their own people only
    assert api.post(t["a"], f"/projects/{proj['id']}/tasks", {"title": "Hack", "assignee_id": u["a"]["id"]}).status_code == 403
    r = api.post(t["lead"], f"/projects/{proj['id']}/tasks", {"title": "Build login", "assignee_id": u["a"]["id"], "priority": "high", "due_date": due, "description": "Own the login screen"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["assignee_id"] == u["a"]["id"] and task["priority"] == "high"
    assert api.post(t["lead"], f"/projects/{proj['id']}/tasks", {"title": "Outside", "assignee_id": u["c"]["id"]}).status_code == 403
    assert api.post(t["lead"], f"/projects/{proj['id']}/tasks", {"title": "Self", "assignee_id": u["lead"]["id"]}).status_code == 201
    assert api.post(t["lead2"], f"/projects/{proj['id']}/tasks", {"title": "Not my team"}).status_code in (403, 404)
    # leader may reassign / re-prioritise inside the team, but not mark done or hand out to outsiders
    assert api.patch(t["lead"], f"/tasks/{task['id']}", {"assignee_id": u["b"]["id"], "priority": "urgent"}).json()["assignee_id"] == u["b"]["id"]
    assert api.patch(t["lead"], f"/tasks/{task['id']}", {"assignee_id": u["c"]["id"]}).status_code == 403
    assert api.patch(t["lead"], f"/tasks/{task['id']}", {"status": "done"}).status_code == 403
    assert api.delete(t["lead"], f"/tasks/{task['id']}").status_code == 403
    # assignee works the task and flags a blocker -> leader and manager are notified
    assert api.patch(t["b"], f"/tasks/{task['id']}", {"title": "rename"}).status_code == 403
    r = api.patch(t["b"], f"/tasks/{task['id']}", {"status": "in_progress", "progress": 40, "is_blocked": True, "blocker_note": "Waiting on API keys"})
    assert r.status_code == 200 and r.json()["is_blocked"] is True
    assert "Task blocked" in [n["title"] for n in api.get(t["lead"], "/notifications").json()["items"]]
    assert "Task blocked" in [n["title"] for n in api.get(t["mgr"], "/notifications").json()["items"]]
    detail = api.get(t["lead"], f"/teams/{tid}").json()
    assert detail["blockers"]["tasks"][0]["note"] == "Waiting on API keys"
    assert next(m for m in detail["members"] if m["id"] == u["b"]["id"])["blocked_tasks"] == 1
    # unblock, then submit for review -> manager approves (done clears the blocker)
    assert api.patch(t["b"], f"/tasks/{task['id']}", {"is_blocked": False}).json()["blocker_note"] is None
    assert api.patch(t["b"], f"/tasks/{task['id']}", {"status": "review"}).status_code == 200
    assert api.post(t["mgr"], f"/tasks/{task['id']}/review", {"approved": True}).json()["status"] == "done"
    # project detail tells the UI what a leader may do
    pd = api.get(t["lead"], f"/projects/{proj['id']}").json()
    assert pd["can_assign_tasks"] and not pd["can_edit"] and set(pd["assignable_ids"]) == set(ids(co, "a", "b", "lead"))


def test_progress_overdue_and_analytics(api, co):
    t, u = co["t"], co["u"]
    team = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    proj = next(p for p in api.get(t["mgr"], f"/teams/{team['id']}").json()["projects"] if p["name"] == "Mobile app")
    past = (utcnow().date() - timedelta(days=3)).isoformat()
    api.post(t["lead"], f"/projects/{proj['id']}/tasks", {"title": "Late work", "assignee_id": u["a"]["id"], "due_date": past})
    api.post(t["mgr"], f"/projects/{proj['id']}/milestones", {"title": "Beta", "due_date": past})
    d = api.get(t["mgr"], f"/teams/{team['id']}").json()
    p = d["projects"][0]
    assert p["overdue_tasks"] >= 1 and p["milestones_total"] == 1 and p["overdue_milestones"] == 1 and p["next_milestone"]["title"] == "Beta"
    assert d["overdue_tasks"] >= 1 and d["done_count"] >= 1 and d["done_last_30d"] >= 1 and d["on_time_rate"] is not None
    assert next(m for m in d["members"] if m["id"] == u["a"]["id"])["overdue_tasks"] >= 1
    # plain members see the roster and projects, but not workloads / blockers
    md = api.get(t["a"], f"/teams/{team['id']}").json()
    assert "blockers" not in md and "open_tasks" not in md["members"][0] and not md["can_monitor"] and md["is_member"]
    # analytics: scoped per role
    a = api.get(t["mgr"], "/teams/analytics").json()
    row = next(i for i in a["items"] if i["team_id"] == team["id"])
    assert row["members"] == 3 and row["overdue_tasks"] >= 1 and row["completion_rate"] > 0
    assert all(i["team_id"] != team["id"] for i in api.get(t["mgr2"], "/teams/analytics").json()["items"])
    assert api.get(t["a"], "/teams/analytics").status_code == 403


# ---- daily updates & reports ---------------------------------------------------------------------------

def test_leader_tracks_daily_updates_and_reports_to_manager(api, co):
    t, u = co["t"], co["u"]
    team = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    tid = team["id"]
    today = utcnow().date().isoformat()
    r = api.post(t["a"], "/daily-updates", {"work_date": today, "completed": "Login form", "hours_worked": 6, "blockers": "Need API keys"})
    assert r.status_code == 201
    assert "Daily update submitted" in [n["title"] for n in api.get(t["lead"], "/notifications").json()["items"]]
    ups = api.get(t["lead"], f"/teams/{tid}/updates").json()
    assert ups["submitted"] == 1 and ups["missing"] == 2
    item = next(i for i in ups["items"] if i["user_id"] == u["a"]["id"])
    assert item["update"]["has_blockers"]
    assert any(b["blockers"] == "Need API keys" for b in api.get(t["lead"], f"/teams/{tid}").json()["blockers"]["updates"])
    # plain members and outsiders cannot read the team's updates; the leader can review
    assert api.get(t["b"], f"/teams/{tid}/updates").status_code == 403
    assert api.get(t["c"], f"/teams/{tid}/updates").status_code == 404
    uid = item["update"]["id"]
    assert api.post(t["b"], f"/teams/{tid}/updates/{uid}/review", {"status": "reviewed"}).status_code == 403
    assert api.post(t["lead"], f"/teams/{tid}/updates/{uid}/review", {"status": "reviewed", "comment": "ok"}).json()["review_status"] == "reviewed"
    # progress report: leader only, then the manager reads it
    assert api.post(t["a"], f"/teams/{tid}/reports", {"summary": "all good"}).status_code == 403
    assert api.post(t["mgr"], f"/teams/{tid}/reports", {"summary": "manager cannot file for the leader"}).status_code == 403
    r = api.post(t["lead"], f"/teams/{tid}/reports", {"summary": "On track, one blocker on API keys", "health": "at_risk"})
    assert r.status_code == 201
    assert any("at risk" in n["title"] for n in api.get(t["mgr"], "/notifications").json()["items"])
    reps = api.get(t["mgr"], f"/teams/{tid}/reports").json()["items"]
    assert reps and reps[0]["health"] == "at_risk" and reps[0]["author_name"]
    assert api.get(t["a"], f"/teams/{tid}/reports").status_code == 403
    assert api.post(t["lead"], f"/teams/{tid}/reports", {"summary": "x"}).status_code == 422


def test_my_teams_view_for_members(api, co):
    mine = api.get(co["t"]["b"], "/teams/mine").json()["items"]
    assert len(mine) == 1 and mine[0]["name"] == "Alpha" and mine[0]["leader"]["id"] == co["u"]["lead"]["id"]
    assert api.get(co["t"]["free"], "/teams/mine").json()["items"] == []
    assert api.get(co["t"]["lead"], "/teams/mine").json()["items"][0]["can_lead"] is True


# ---- transfers, reassignment, deletion ------------------------------------------------------------------

def test_transfers_between_teams_and_branches(api, co):
    t, u, f = co["t"], co["u"], co["f"]
    alpha = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    bravo = api.get(t["mgr2"], "/teams?q=bravo").json()["items"][0]
    south_team = api.post(t["mgr_s"], "/teams", {"name": "Delta", "member_ids": ids(co, "s1")}).json()
    # who may transfer
    for who in ("mgr", "lead", "a"):
        assert api.post(t[who], "/teams/transfer", {"user_id": u["a"]["id"], "to_team_id": bravo["id"]}).status_code == 403
    assert api.post(t["hr_n"], "/teams/transfer", {"user_id": u["a"]["id"], "to_team_id": alpha["id"]}).status_code == 400  # already there
    # HR moves 'a' (who still has open work) Alpha -> Bravo: tasks are freed, leaders hear about it
    r = api.post(t["hr_n"], "/teams/transfer", {"user_id": u["a"]["id"], "to_team_id": bravo["id"], "note": "Reorg"})
    assert r.status_code == 200 and r.json()["unassigned_tasks"] >= 1 and not r.json()["branch_changed"]
    members = lambda team: {m["id"] for m in api.get(f, f"/teams/{team['id']}").json()["members"]}
    assert u["a"]["id"] in members(bravo) and u["a"]["id"] not in members(alpha)
    my = api.get(t["a"], "/tasks/mine").json()["items"]
    assert all(x["status"] == "done" for x in my)
    # access to Alpha's project is gone, Bravo has none yet
    assert api.get(t["a"], "/teams/mine").json()["items"][0]["name"] == "Bravo"
    # HR (north) cannot move someone across branches; only a founder can, and the person's branch follows
    assert api.post(t["hr_n"], "/teams/transfer", {"user_id": u["a"]["id"], "to_team_id": south_team["id"]}).status_code in (403, 404)
    r = api.post(f, "/teams/transfer", {"user_id": u["a"]["id"], "to_team_id": south_team["id"]})
    assert r.status_code == 200 and r.json()["branch_changed"]
    assert api.get(f, f"/employees/{u['a']['id']}").json()["branch_id"] == co["south"]["id"]
    # founders / unknown people cannot be transferred
    fid = api.get(f, "/auth/me").json()["id"]
    assert api.post(f, "/teams/transfer", {"user_id": fid, "to_team_id": bravo["id"]}).status_code == 404
    acts = api.get(f, "/admin/audit-logs?action=team.member_transferred&page_size=50").json()["items"]
    assert any(a["detail"]["branch_changed"] for a in acts) and any(a["detail"]["note"] == "Reorg" for a in acts)


def test_leaving_a_team_clears_leadership_and_branch_changes_release_members(api, co):
    t, u, f = co["t"], co["u"], co["f"]
    bravo = api.get(t["mgr2"], "/teams?q=bravo").json()["items"][0]
    assert bravo["leader_id"] == u["lead2"]["id"]
    # moving the leader's branch removes them from the (north) team and clears the leader slot
    api.post(f, f"/branches/{co['south']['id']}/members", {"user_ids": [u["lead2"]["id"]]})
    d = api.get(t["mgr2"], f"/teams/{bravo['id']}").json()
    assert d["leader_id"] is None and u["lead2"]["id"] not in {m["id"] for m in d["members"]}


def test_reassign_edit_and_delete_team(api, co):
    t, u, f = co["t"], co["u"], co["f"]
    alpha = api.get(t["mgr"], "/teams?q=alpha").json()["items"][0]
    tid = alpha["id"]
    # edit: manager/founder only
    assert api.patch(t["lead"], f"/teams/{tid}", {"name": "Hacked"}).status_code == 403
    assert api.patch(t["hr_n"], f"/teams/{tid}", {"name": "Hacked"}).status_code == 403
    assert api.patch(t["mgr"], f"/teams/{tid}", {"name": "Alpha Squad", "description": "Core product"}).json()["name"] == "Alpha Squad"
    assert api.patch(t["mgr"], f"/teams/{tid}", {"name": "bravo"}).status_code == 409
    assert api.patch(t["mgr"], f"/teams/{tid}", {"branch_id": co["south"]["id"]}).status_code == 403
    # reassign to another manager of the branch (also needed: the receiving manager must be a manager)
    assert api.post(t["lead"], f"/teams/{tid}/reassign", {"manager_id": u["mgr2"]["id"]}).status_code == 403
    assert api.post(t["mgr"], f"/teams/{tid}/reassign", {"manager_id": u["a"]["id"]}).status_code == 400
    assert api.post(t["mgr"], f"/teams/{tid}/reassign", {"manager_id": u["mgr_s"]["id"]}).status_code == 400  # other branch
    r = api.post(t["mgr"], f"/teams/{tid}/reassign", {"manager_id": u["mgr2"]["id"]})
    assert r.status_code == 200 and r.json()["manager_id"] == u["mgr2"]["id"]
    assert api.get(t["mgr"], f"/teams/{tid}").status_code == 404  # the old manager lost access
    assert api.patch(t["mgr"], f"/teams/{tid}", {"is_active": False}).status_code == 404
    # a task-less member's project access follows the team
    assert api.post(t["mgr2"], f"/teams/{tid}/members", {"user_ids": ids(co, "free")}).status_code == 200
    pid0 = api.get(t["mgr2"], f"/teams/{tid}").json()["projects"][0]["id"]
    assert any(x["id"] == pid0 for x in api.get(t["free"], "/projects").json()["items"])
    # deactivated teams stop accepting work and lose leader powers; then delete
    assert api.patch(t["mgr2"], f"/teams/{tid}", {"is_active": False}).json()["is_active"] is False
    proj = api.get(t["mgr2"], f"/teams/{tid}").json()["projects"][0]
    assert api.post(t["lead"], f"/projects/{proj['id']}/tasks", {"title": "After deactivation"}).status_code == 403
    assert api.post(t["mgr2"], f"/teams/{tid}/members", {"user_ids": ids(co, "c")}).status_code == 400
    assert api.delete(t["lead"], f"/teams/{tid}").status_code == 403
    assert api.delete(t["mgr2"], f"/teams/{tid}").status_code == 204
    assert api.get(f, f"/teams/{tid}").status_code == 404
    assert api.get(t["b"], "/teams/mine").json()["items"] == []
    assert not any(x["id"] == proj["id"] for x in api.get(t["free"], "/projects").json()["items"])  # project access trimmed
    for action in ("team.updated", "team.reassigned", "team.deleted", "team.project_assigned", "team.member_removed"):
        assert api.get(f, f"/admin/audit-logs?action={action}").json()["total"] >= 1, action


def test_offboarding_removes_person_from_team(api, co):
    f, t = co["f"], co["t"]
    team = make_team(api, co, "Echo", who="mgr2", members=("free",), leader="free")
    c_id = co["u"]["free"]["id"]
    assert team["leader_id"] == c_id
    assert api.post(f, f"/employees/{c_id}/offboard").status_code == 200
    d = api.get(f, f"/teams/{team['id']}").json()
    assert d["leader_id"] is None
    assert c_id not in {m["id"] for m in d["members"]}


def test_board_members_and_tenant_isolation(api, co):
    f = co["f"]
    board = api.post(f, "/board/members", {"email": "board@teamco.com", "full_name": "Bo Ard", "password": "Str0ng-Pw-12"})
    assert board.status_code in (200, 201), board.text
    tok = api.login("teamco", "board@teamco.com")
    assert api.get(tok, "/teams").status_code == 403
    # a different company never sees these teams, even with the same numeric ids
    api.make_company("teamco2")
    f2 = api.login("teamco2", "founder@teamco2.com")
    assert api.get(f2, "/teams").json()["total"] == 0
    for tid in (1, 2, 3):
        assert api.get(f2, f"/teams/{tid}").status_code == 404
    mine = api.post(f2, "/teams", {"name": "Alpha Squad"})
    assert mine.status_code == 201  # same name is fine in another tenant
    assert api.get(f, "/teams?q=bravo").json()["total"] >= 1


def test_listing_filters_and_pagination(api, co):
    f = co["f"]
    r = api.get(f, "/teams?page_size=2").json()
    assert len(r["items"]) <= 2 and r["total"] >= 3
    north = api.get(f, f"/teams?branch_id={co['north']['id']}").json()
    assert north["total"] >= 1 and all(i["branch_id"] == co["north"]["id"] for i in north["items"])
    assert all(i["is_active"] for i in api.get(f, "/teams?active=true").json()["items"])
    # members only see their own team in the list
    mine = api.get(co["t"]["s1"], "/teams").json()["items"]
    assert [i["name"] for i in mine] == ["Delta"]


def test_available_people_pool(api, co):
    f, t = co["f"], co["t"]
    pool = api.get(t["mgr"], "/teams/available").json()["items"]
    assert pool and all(p["branch_id"] == co["north"]["id"] for p in pool)  # branch manager only sees their branch
    assert all(p["role"] in ("employee", "manager", "hr") for p in pool)
    assert api.get(t["a"], "/teams/available").status_code == 403
    in_team = {m["id"] for tm in api.get(f, "/teams").json()["items"] for m in api.get(f, f"/teams/{tm['id']}").json()["members"]}
    assert not ({p["id"] for p in api.get(f, "/teams/available").json()["items"]} & in_team)


# ---- new project with team leader + members, active-team availability, DB-level uniqueness ---------------------

def fresh(api, co, name, role="employee"):
    return api.add_user(co["f"], f"{name}@teamco.com", role, branch_id=co["north"]["id"])


def pool_ids(api, tok):
    return {p["id"] for p in api.get(tok, "/teams/available").json()["items"]}


def test_new_project_creates_team_with_leader_and_members_atomically(api, co):
    t = co["t"]
    lead, m1, m2 = fresh(api, co, "np_lead"), fresh(api, co, "np_m1"), fresh(api, co, "np_m2")
    assert {lead["id"], m1["id"], m2["id"]} <= pool_ids(api, t["mgr"])
    r = api.post(t["mgr"], "/projects", {"name": "Billing revamp", "team": {"leader_id": lead["id"], "member_ids": [m1["id"]]}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    team = api.get(t["mgr"], "/teams?q=billing").json()["items"][0]
    assert team["name"] == "Billing revamp Team" and team["leader_id"] == lead["id"] and team["project_count"] == 1 and team["member_count"] == 2
    # the new members can see the project; others cannot
    assert any(p["id"] == pid for p in api.get(api.login("teamco", "np_m1@teamco.com"), "/projects").json()["items"])
    assert not any(p["id"] == pid for p in api.get(api.login("teamco", "np_m2@teamco.com"), "/projects").json()["items"])
    # they are no longer offered to other teams and cannot be added to one (API check)
    assert not ({lead["id"], m1["id"]} & pool_ids(api, t["mgr"])) and m2["id"] in pool_ids(api, t["mgr"])
    assert api.post(t["mgr2"], "/teams", {"name": "Dup", "member_ids": [m1["id"]]}).status_code == 409
    # the new leader runs the team: add/remove members, distribute tasks, see updates and progress
    lead_tok = api.login("teamco", "np_lead@teamco.com")
    assert api.post(lead_tok, f"/teams/{team['id']}/members", {"user_ids": [m2["id"]]}).status_code == 200
    assert api.post(lead_tok, f"/projects/{pid}/tasks", {"title": "Kickoff", "assignee_id": m2["id"]}).status_code == 201
    assert api.get(lead_tok, f"/teams/{team['id']}/updates").status_code == 200
    assert lead["id"] not in {p["id"] for p in api.get(lead_tok, "/teams/available").json()["items"]}
    d = api.get(lead_tok, f"/teams/{team['id']}").json()
    assert d["can_lead"] and d["can_manage_members"] and not d["can_manage"] and d["task_count"] == 1
    # leaders cannot remove the leader slot, replace the leader or delete the team
    assert api.delete(lead_tok, f"/teams/{team['id']}/members/{lead['id']}").status_code == 403
    assert api.put(lead_tok, f"/teams/{team['id']}/leader", {"user_id": m2["id"]}).status_code == 403
    assert api.delete(lead_tok, f"/teams/{team['id']}").status_code == 403
    assert api.delete(lead_tok, f"/teams/{team['id']}/members/{m2['id']}").status_code == 200
    # manager keeps full control, HR can still manage the assignments
    assert api.delete(t["hr_n"], f"/teams/{team['id']}/members/{m1['id']}").status_code == 200
    assert api.put(t["mgr"], f"/teams/{team['id']}/leader", {"user_id": None}).status_code == 200


def test_project_team_validation_rolls_back_and_permissions(api, co):
    t, u = co["t"], co["u"]
    taken = fresh(api, co, "pv_taken")
    api.post(t["mgr2"], "/teams", {"name": "Holders", "member_ids": [taken["id"]]})
    before = api.get(t["mgr"], "/projects?page_size=100").json()["total"]
    # someone already in an active team -> 409 and no project is created
    r = api.post(t["mgr"], "/projects", {"name": "Should not exist", "team": {"member_ids": [taken["id"]]}})
    assert r.status_code == 409 and "already in team Holders" in r.json()["error"]["message"]
    # wrong branch / non-eligible people / duplicate team name
    assert api.post(t["mgr"], "/projects", {"name": "Nope1", "team": {"member_ids": [u["s1"]["id"]]}}).status_code == 400
    assert api.post(t["mgr"], "/projects", {"name": "Nope2", "team": {"leader_id": u["hr_n"]["id"]}}).status_code == 400
    assert api.post(t["mgr"], "/projects", {"name": "Nope3", "team": {"name": "Holders"}}).status_code == 409
    assert api.get(t["mgr"], "/projects?page_size=100").json()["total"] == before
    # HR may create projects but not project teams; choosing both options is rejected
    assert api.post(t["hr_n"], "/projects", {"name": "HR proj", "team": {"member_ids": []}}).status_code == 403
    holders = api.get(t["mgr2"], "/teams?q=holders").json()["items"][0]
    assert api.post(t["mgr2"], "/projects", {"name": "Both", "team_id": holders["id"], "team": {}}).status_code == 400
    # allocate a new project to an existing team you manage; not to someone else's team
    r = api.post(t["mgr2"], "/projects", {"name": "Holders phase 1", "team_id": holders["id"]})
    assert r.status_code == 201
    assert any(p["id"] == r.json()["id"] for p in api.get(t["mgr2"], f"/teams/{holders['id']}").json()["projects"])
    assert api.post(t["mgr"], "/projects", {"name": "Steal", "team_id": holders["id"]}).status_code == 404
    assert api.post(t["mgr"], "/projects", {"name": "Ghost", "team_id": 99999}).status_code == 404


def test_inactive_team_members_are_available_again_and_db_blocks_duplicates(api, co):
    t = co["t"]
    p1 = fresh(api, co, "in_p1")
    old = api.post(t["mgr2"], "/teams", {"name": "Yankee", "member_ids": [p1["id"]]}).json()
    assert p1["id"] not in pool_ids(api, t["mgr"])
    # deactivated team: its members are selectable again; joining another team drops the stale membership
    api.patch(t["mgr2"], f"/teams/{old['id']}", {"is_active": False})
    assert p1["id"] in pool_ids(api, t["mgr"])
    assert api.post(t["mgr2"], "/teams", {"name": "Xray", "member_ids": [p1["id"]]}).status_code == 201
    assert p1["id"] not in {m["id"] for m in api.get(t["mgr2"], f"/teams/{old['id']}").json()["members"]}
    assert p1["id"] not in pool_ids(api, t["mgr"])
    # the database itself refuses a second membership row for the same person
    from sqlalchemy import insert, select
    from sqlalchemy.exc import IntegrityError
    from app.db.platform_models import Company
    from app.db.session import platform_session
    from app.db.tenant_models import TeamMember
    from app.tenancy.manager import tenants
    with platform_session() as pdb:
        company = pdb.scalar(select(Company).where(Company.slug == "teamco"))
        pdb.expunge(company)
    with tenants.session_for(company) as db:
        with pytest.raises(IntegrityError):
            db.execute(insert(TeamMember).values(team_id=old["id"], user_id=p1["id"]))
            db.commit()


def test_manager_can_add_and_list_their_employees_but_not_edit_or_escalate(api, co):
    t, u, f = co["t"], co["u"], co["f"]
    r = api.post(t["mgr"], "/employees", {"email": "newhire@teamco.com", "full_name": "New Hire", "password": "Str0ng-Pw-12", "role": "employee"})
    assert r.status_code == 201, r.text
    hire = r.json()
    assert hire["manager_id"] == u["mgr"]["id"] and hire["branch_id"] == co["north"]["id"]  # reports to the creator, in their branch
    # roles above employee, other branches and foreign reporting lines are refused / overridden
    assert api.post(t["mgr"], "/employees", {"email": "x1@teamco.com", "full_name": "X One", "password": "Str0ng-Pw-12", "role": "manager"}).status_code == 403
    assert api.post(t["mgr"], "/employees", {"email": "x2@teamco.com", "full_name": "X Two", "password": "Str0ng-Pw-12", "branch_id": co["south"]["id"]}).status_code == 403
    r = api.post(t["mgr"], "/employees", {"email": "x3@teamco.com", "full_name": "X Three", "password": "Str0ng-Pw-12", "manager_id": u["mgr2"]["id"]})
    assert r.status_code == 201 and r.json()["manager_id"] == u["mgr"]["id"]
    # the list shows only the manager's own reports; the other manager sees none of them
    mine = {e["id"] for e in api.get(t["mgr"], "/employees?page_size=100").json()["items"]}
    assert hire["id"] in mine and u["mgr2"]["id"] not in mine and u["a"]["id"] not in mine
    assert hire["id"] not in {e["id"] for e in api.get(t["mgr2"], "/employees?page_size=100").json()["items"]}
    # manager has CRUD access to their own reports
    assert api.get(t["mgr"], f"/employees/{hire['id']}").status_code == 200
    assert api.get(t["mgr2"], f"/employees/{hire['id']}").status_code == 403
    assert api.patch(t["mgr"], f"/employees/{hire['id']}", {"designation": "Boss"}).status_code == 200
    assert api.delete(t["mgr"], f"/employees/{hire['id']}").status_code == 204
    # plain employees still have no access; the permission can be withdrawn
    assert api.get(t["a"], "/employees").status_code == 403 and api.post(t["a"], "/employees", {"email": "y@teamco.com", "full_name": "Y Y", "password": "Str0ng-Pw-12"}).status_code == 403
    api.patch(f, f"/managers/{u['mgr2']['id']}", {"permissions": ["projects.manage"]})
    assert api.get(t["mgr2"], "/employees").status_code == 403
    api.patch(f, f"/managers/{u['mgr2']['id']}", {"permissions": None})


def test_manager_added_employee_needs_hr_or_founder_approval(api, co):
    t, u, f = co["t"], co["u"], co["f"]
    hire = api.post(t["mgr"], "/employees", {"email": "pending1@teamco.com", "full_name": "Pending One", "password": "Str0ng-Pw-12"}).json()
    assert hire["status"] == "pending_approval" and hire["is_active"] is False
    # cannot sign in or join a team yet; employees created by HR/founder are unaffected
    assert api.c.post("/api/v1/auth/login", json={"company_slug": "teamco", "email": "pending1@teamco.com", "password": "Str0ng-Pw-12"}).status_code == 401
    assert api.post(t["mgr"], "/teams", {"name": "Pending team", "member_ids": [hire["id"]]}).status_code == 400
    assert hire["id"] not in {p["id"] for p in api.get(t["mgr"], "/teams/available").json()["items"]}
    assert api.add_user(f, "direct@teamco.com", "employee")["status"] == "onboarding"
    # HR and the founder are told; nobody else may decide
    for who in ("hr_n", "hr_all"):
        assert "Employee awaiting approval" in [n["title"] for n in api.get(t[who], "/notifications").json()["items"]]
    for who in ("mgr2", "a"):
        assert api.post(t[who], f"/employees/{hire['id']}/approve").status_code == 403
    for who in ("mgr2", "a"):  # only HR/founder or the manager who added the joining may delete it
        assert api.post(t[who], f"/employees/{hire['id']}/reject").status_code == 403
    assert api.patch(t["hr_n"], f"/employees/{hire['id']}", {"status": "active"}).status_code == 400
    assert api.post(t["hr_n"], f"/employees/{hire['id']}/offboard").status_code == 409
    r = api.post(t["hr_n"], f"/employees/{hire['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["is_active"] is True
    assert api.post(t["hr_n"], f"/employees/{hire['id']}/approve").status_code == 409
    assert "Joining approved" in [n["title"] for n in api.get(t["mgr"], "/notifications").json()["items"]]
    assert api.login("teamco", "pending1@teamco.com")
    # rejection removes the account and only applies to pending joinings
    nope = api.post(t["mgr"], "/employees", {"email": "pending2@teamco.com", "full_name": "Pending Two", "password": "Str0ng-Pw-12"}).json()
    assert api.post(f, f"/employees/{nope['id']}/reject").status_code == 204
    assert api.get(f, f"/employees/{nope['id']}").status_code == 404
    assert api.post(f, f"/employees/{u['a']['id']}/reject").status_code == 409
    acts = {a["action"] for a in api.get(f, "/admin/audit-logs?action=employee.&page_size=100").json()["items"]}
    assert {"employee.approved", "employee.rejected"} <= acts


def test_manager_can_add_hr_but_only_a_founder_approves_it(api, co):
    t, f = co["t"], co["f"]
    r = api.post(t["mgr"], "/employees", {"email": "newhr@teamco.com", "full_name": "New Hr", "password": "Str0ng-Pw-12", "role": "hr"})
    assert r.status_code == 201 and r.json()["role"] == "hr" and r.json()["status"] == "pending_approval" and r.json()["branch_id"] == co["north"]["id"]
    hid = r.json()["id"]
    assert api.post(t["mgr"], "/employees", {"email": "newmgr@teamco.com", "full_name": "New Mgr", "password": "Str0ng-Pw-12", "role": "manager"}).status_code == 403
    assert api.post(t["hr_n"], f"/employees/{hid}/approve").status_code == 403  # HR cannot mint HR
    assert api.post(t["mgr2"], f"/employees/{hid}/approve").status_code == 403  # a manager the HR hire does not report to
    assert api.post(f, f"/employees/{hid}/approve").json()["is_active"] is True
    assert api.login("teamco", "newhr@teamco.com")


def test_manager_can_delete_only_their_own_pending_joining(api, co):
    t, f = co["t"], co["f"]
    mine = api.post(t["mgr"], "/employees", {"email": "withdraw@teamco.com", "full_name": "With Draw", "password": "Str0ng-Pw-12"}).json()
    assert api.post(t["mgr2"], f"/employees/{mine['id']}/reject").status_code == 403  # someone else's joining
    assert api.post(t["mgr"], f"/employees/{co['u']['a']['id']}/reject").status_code == 403  # not pending
    assert api.post(t["mgr2"], f"/employees/{mine['id']}/approve").status_code == 403  # only HR/founder or the adding manager
    assert api.post(t["mgr"], f"/employees/{mine['id']}/reject").status_code == 204
    assert api.get(f, f"/employees/{mine['id']}").status_code == 404


def test_every_team_member_sees_who_works_on_each_project(api, co):
    t = co["t"]
    lead, m1, m2 = fresh(api, co, "pv2_lead"), fresh(api, co, "pv2_m1"), fresh(api, co, "pv2_m2")
    r = api.post(t["mgr"], "/projects", {"name": "Visibility", "team": {"leader_id": lead["id"], "member_ids": [m1["id"], m2["id"]]}})
    pid = r.json()["id"]
    lead_tok = api.login("teamco", "pv2_lead@teamco.com")
    api.post(lead_tok, f"/projects/{pid}/tasks", {"title": "Wire the API", "assignee_id": m1["id"], "due_date": str(utcnow().date() + timedelta(days=2))})
    team = api.get(t["mgr"], "/teams?q=visibility").json()["items"][0]
    member_tok = api.login("teamco", "pv2_m2@teamco.com")
    d = api.get(member_tok, f"/teams/{team['id']}").json()
    assert not d["can_monitor"]
    people = {x["id"]: x for x in d["projects"][0]["people"]}
    assert set(people) == {lead["id"], m1["id"], m2["id"]} and people[lead["id"]]["is_leader"]
    assert people[m1["id"]]["open_tasks"] == 1 and people[m1["id"]]["tasks"][0]["title"] == "Wire the API"
    assert people[m2["id"]]["tasks"] == []
    # someone outside the team does not get this
    assert api.get(t["c"], f"/teams/{team['id']}").status_code == 404


def test_employee_temporary_password_must_be_4_to_12_characters(api, co):
    f, t = co["f"], co["t"]
    base = {"full_name": "Pw Check", "role": "employee"}
    for bad in ("abc", "x" * 13, ""):
        r = api.post(f, "/employees", {**base, "email": "pwbad@teamco.com", "password": bad})
        assert r.status_code == 422, bad
    ok = api.post(f, "/employees", {**base, "email": "pw4@teamco.com", "password": "abcd"})
    assert ok.status_code == 201 and api.login("teamco", "pw4@teamco.com", "abcd")
    assert api.post(f, "/employees", {**base, "email": "pw12@teamco.com", "password": "123456789012"}).status_code == 201
    uid = ok.json()["id"]
    assert api.post(f, f"/employees/{uid}/reset-password", {"new_password": "abc"}).status_code == 422
    assert api.post(f, f"/employees/{uid}/reset-password", {"new_password": "x" * 13}).status_code == 422
    assert api.post(f, f"/employees/{uid}/reset-password", {"new_password": "wxyz"}).status_code == 204
    assert api.login("teamco", "pw4@teamco.com", "wxyz")
    # a manager's new joining follows the same rule; the person's own password change keeps the stronger policy
    assert api.post(t["mgr"], "/employees", {**base, "email": "pwm@teamco.com", "password": "ab"}).status_code == 422
    tok = api.login("teamco", "pw4@teamco.com", "wxyz")
    assert api.post(tok, "/auth/change-password", {"current_password": "wxyz", "new_password": "short"}).status_code == 422
