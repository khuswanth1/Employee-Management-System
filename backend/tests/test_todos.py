"""Personal task manager: tasks, subtasks, priority, duration, status, ordering, privacy."""


def mk(api, tok, title="Task", **kw):
    r = api.post(tok, "/todos", {"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def tree(api, tok):
    return api.get(tok, "/todos").json()


def titles(api, tok):
    return [t["title"] for t in tree(api, tok)["items"]]


def test_crud_and_defaults(api, org):
    t = org["emp"]
    a = mk(api, t, "  Write   report  ", priority="high", duration_minutes=90, notes="  first draft  ")
    assert a["title"] == "Write report" and a["priority"] == "high" and a["status"] == "todo"
    assert a["duration_minutes"] == 90 and a["notes"] == "first draft" and a["subtasks"] == []
    r = api.patch(t, f"/todos/{a['id']}", {"title": "Write the report ✨", "priority": "low", "status": "in_progress", "duration_minutes": None})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Write the report ✨" and body["priority"] == "low" and body["status"] == "in_progress"
    assert body["duration_minutes"] is None
    assert api.delete(t, f"/todos/{a['id']}").status_code == 204
    assert api.get(t, f"/todos").json()["items"] == []


def test_persistence_between_requests_and_order(api, org):
    t = org["emp2"]
    for n in ("one", "two", "three"):
        mk(api, t, n)
    assert titles(api, t) == ["one", "two", "three"]
    again = api.get(t, "/todos").json()
    assert [i["position"] for i in again["items"]] == [0, 1, 2]


def test_subtasks_belong_to_their_parent_and_have_their_own_fields(api, org):
    t = org["emp"]
    p = mk(api, t, "Parent", duration_minutes=60)
    s1 = mk(api, t, "Sub A", parent_id=p["id"], priority="high", duration_minutes=30)
    s2 = mk(api, t, "Sub B", parent_id=p["id"], priority="low", duration_minutes=15)
    top = [i for i in tree(api, t)["items"] if i["id"] == p["id"]][0]
    assert [s["title"] for s in top["subtasks"]] == ["Sub A", "Sub B"]
    assert [s["priority"] for s in top["subtasks"]] == ["high", "low"]
    assert top["subtask_count"] == 2 and top["subtasks_done"] == 0
    assert top["total_minutes"] == 105 and top["remaining_minutes"] == 105
    # edit a subtask like a main task
    r = api.patch(t, f"/todos/{s1['id']}", {"title": "Sub A2", "duration_minutes": 45, "status": "completed"})
    assert r.status_code == 200 and r.json()["parent_id"] == p["id"]
    top = [i for i in tree(api, t)["items"] if i["id"] == p["id"]][0]
    assert top["subtasks_done"] == 1 and top["total_minutes"] == 120 and top["remaining_minutes"] == 75
    assert api.delete(t, f"/todos/{s2['id']}").status_code == 204
    top = [i for i in tree(api, t)["items"] if i["id"] == p["id"]][0]
    assert [s["title"] for s in top["subtasks"]] == ["Sub A2"]


def test_status_rules_between_parent_and_subtasks(api, org):
    t = org["mgr"]
    p = mk(api, t, "Release")
    a = mk(api, t, "build", parent_id=p["id"])
    b = mk(api, t, "ship", parent_id=p["id"])
    get = lambda: [i for i in tree(api, t)["items"] if i["id"] == p["id"]][0]
    api.patch(t, f"/todos/{a['id']}", {"status": "in_progress"})
    assert get()["status"] == "in_progress"                       # work on a subtask starts the task
    api.patch(t, f"/todos/{a['id']}", {"status": "completed"})
    assert get()["status"] == "in_progress"
    api.patch(t, f"/todos/{b['id']}", {"status": "completed"})
    assert get()["status"] == "completed" and get()["completed_at"]  # last subtask done completes the task
    api.patch(t, f"/todos/{b['id']}", {"status": "todo"})
    assert get()["status"] == "in_progress"                       # reopening a subtask reopens the task
    api.patch(t, f"/todos/{p['id']}", {"status": "completed"})
    assert all(s["status"] == "completed" for s in get()["subtasks"])  # completing the task completes its subtasks


def test_delete_main_task_deletes_its_subtasks(api, org):
    t = org["emp"]
    p = mk(api, t, "Doomed")
    s = mk(api, t, "child", parent_id=p["id"])
    assert api.delete(t, f"/todos/{p['id']}").status_code == 204
    assert api.patch(t, f"/todos/{s['id']}", {"title": "x"}).status_code == 404


def test_reorder_main_tasks(api, org):
    t = org["hr"]
    ids = [mk(api, t, n)["id"] for n in ("a", "b", "c", "d")]
    r = api.post(t, f"/todos/{ids[3]}/move", {"parent_id": None, "index": 0})
    assert r.status_code == 200
    assert [i["title"] for i in r.json()["items"]] == ["d", "a", "b", "c"]
    r = api.post(t, f"/todos/{ids[3]}/move", {"parent_id": None, "index": 99})
    assert [i["title"] for i in r.json()["items"]] == ["a", "b", "c", "d"]
    assert [i["position"] for i in r.json()["items"]] == [0, 1, 2, 3]


def test_reorder_subtasks_and_move_between_parents(api, org):
    t = org["emp"]
    p1, p2 = mk(api, t, "P1"), mk(api, t, "P2")
    s = [mk(api, t, n, parent_id=p1["id"])["id"] for n in ("s1", "s2", "s3")]
    r = api.post(t, f"/todos/{s[2]}/move", {"parent_id": p1["id"], "index": 0})
    sub = lambda body, pid: [x for x in body["items"] if x["id"] == pid][0]["subtasks"]
    assert [x["title"] for x in sub(r.json(), p1["id"])] == ["s3", "s1", "s2"]
    r = api.post(t, f"/todos/{s[0]}/move", {"parent_id": p2["id"], "index": 0})   # to another task
    assert [x["title"] for x in sub(r.json(), p2["id"])] == ["s1"]
    assert [x["title"] for x in sub(r.json(), p1["id"])] == ["s3", "s2"]
    assert [x["position"] for x in sub(r.json(), p1["id"])] == [0, 1]
    r = api.post(t, f"/todos/{s[1]}/move", {"parent_id": None, "index": 0})        # promote to a main task
    assert r.json()["items"][0]["title"] == "s2"


def test_depth_and_self_nesting_rules(api, org):
    t = org["emp"]
    p = mk(api, t, "Top")
    s = mk(api, t, "Sub", parent_id=p["id"])
    r = api.post(t, "/todos", {"title": "deep", "parent_id": s["id"]})
    assert 400 <= r.status_code < 500
    other = mk(api, t, "Other")
    assert 400 <= api.post(t, f"/todos/{p['id']}/move", {"parent_id": other["id"], "index": 0}).status_code < 500  # has a subtask
    assert 400 <= api.post(t, f"/todos/{other['id']}/move", {"parent_id": other["id"], "index": 0}).status_code < 500
    assert 400 <= api.post(t, f"/todos/{other['id']}/move", {"parent_id": s["id"], "index": 0}).status_code < 500


def test_validation(api, org):
    t = org["emp"]
    for bad in ({"title": ""}, {"title": "   "}, {"title": "x" * 201}, {"title": "ok", "priority": "urgent"},
                {"title": "ok", "status": "done"}, {"title": "ok", "duration_minutes": -5}, {"title": "ok", "duration_minutes": 10 ** 9},
                {"title": "ok", "notes": "n" * 2001}, {"title": "ok", "parent_id": 999999}):
        r = api.post(t, "/todos", bad)
        assert 400 <= r.status_code < 500, (bad, r.status_code)
    p = mk(api, t, "valid")
    assert 400 <= api.patch(t, f"/todos/{p['id']}", {"title": None}).status_code < 500
    assert 400 <= api.patch(t, f"/todos/{p['id']}", {"status": None}).status_code < 500
    assert 400 <= api.post(t, f"/todos/{p['id']}/move", {"parent_id": None, "index": -1}).status_code < 500


def test_tasks_are_private_to_their_owner(api, org):
    a, b = org["emp"], org["emp2"]
    mine = mk(api, a, "secret plan")
    assert all(i["title"] != "secret plan" for i in tree(api, b)["items"])
    assert api.patch(b, f"/todos/{mine['id']}", {"title": "hijack"}).status_code == 404
    assert api.delete(b, f"/todos/{mine['id']}").status_code == 404
    assert api.post(b, f"/todos/{mine['id']}/move", {"parent_id": None, "index": 0}).status_code == 404
    assert api.post(b, "/todos", {"title": "sneaky", "parent_id": mine["id"]}).status_code == 404
    assert api.post(org["founder"], "/todos", {"title": "founder's own"}).status_code == 201
    assert all(i["title"] != "founder's own" for i in tree(api, a)["items"])


def test_other_company_cannot_see_tasks(api, org):
    api.ensure_company("globex")
    g = api.login("globex", "founder@globex.com")
    mk(api, g, "globex only")
    assert "globex only" not in titles(api, org["emp"])


def test_requires_login(api):
    assert api.c.get("/api/v1/todos").status_code == 401


def test_summary_counts_and_time(api, org):
    t = api.login("acme", "mgr2@acme.com")
    a = mk(api, t, "A", duration_minutes=60)
    mk(api, t, "B", duration_minutes=30, status="in_progress")
    c = mk(api, t, "C", duration_minutes=20, status="completed")
    mk(api, t, "C1", parent_id=c["id"], duration_minutes=10, status="completed")
    s = api.get(t, "/todos").json()["summary"]
    assert s["total"] == 3 and s["todo"] == 1 and s["in_progress"] == 1 and s["completed"] == 1
    assert s["total_minutes"] == 120 and s["remaining_minutes"] == 90
    assert a["status"] == "todo"


def test_limits(api, org):
    t = api.login("acme", "hr@acme.com")
    p = mk(api, t, "Many subs")
    for i in range(50):
        assert api.post(t, "/todos", {"title": f"s{i}", "parent_id": p["id"]}).status_code == 201
    assert 400 <= api.post(t, "/todos", {"title": "one too many", "parent_id": p["id"]}).status_code < 500
