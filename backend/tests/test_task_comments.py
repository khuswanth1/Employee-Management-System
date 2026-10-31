"""Discussion on project tasks: who may read, write and delete, validation, notifications and company isolation."""
import pytest


@pytest.fixture(scope="module")
def tc(api, org):
    f = org["founder"]
    mgr = api.add_user(f, "tc.mgr@acme.com", "manager")
    member = api.add_user(f, "tc.member@acme.com", "employee", manager_id=mgr["id"])
    assignee = api.add_user(f, "tc.assignee@acme.com", "employee", manager_id=mgr["id"])
    outsider = api.add_user(f, "tc.out@acme.com", "employee")
    t = {n: api.login("acme", f"tc.{n}@acme.com") for n in ("mgr", "member", "assignee", "out")}
    p = api.post(t["mgr"], "/projects", {"name": "Discuss me", "member_ids": [member["id"], assignee["id"]]}).json()
    task = api.post(t["mgr"], f"/projects/{p['id']}/tasks", {"title": "Design the API", "assignee_id": assignee["id"]})
    assert task.status_code == 201, task.text
    return {"t": t, "f": f, "task": task.json()["id"], "ids": {"mgr": mgr["id"], "assignee": assignee["id"], "member": member["id"]}}


def test_members_discuss_and_everyone_with_access_can_read(api, tc):
    url = f"/tasks/{tc['task']}/comments"
    assert api.get(tc["t"]["member"], url).json() == {"items": [], "can_comment": True}
    r = api.post(tc["t"]["member"], url, {"body": "  Should we version the endpoints?  "})
    assert r.status_code == 201 and r.json()["body"] == "Should we version the endpoints?" and r.json()["author_id"] == tc["ids"]["member"]
    assert api.post(tc["t"]["assignee"], url, {"body": "Yes, /v1 from the start."}).status_code == 201
    assert api.post(tc["t"]["mgr"], url, {"body": "Agreed."}).status_code == 201
    assert api.post(tc["f"], url, {"body": "Founder checking in."}).status_code == 201
    items = api.get(tc["t"]["assignee"], url).json()["items"]
    assert [c["body"] for c in items] == ["Should we version the endpoints?", "Yes, /v1 from the start.", "Agreed.", "Founder checking in."]  # oldest first
    assert items[0]["author"].startswith("Tc")


def test_validation(api, tc):
    url = f"/tasks/{tc['task']}/comments"
    for bad in ({"body": ""}, {"body": "   "}, {"body": "x" * 2001}, {}):
        assert api.post(tc["t"]["mgr"], url, bad).status_code == 422, bad
    assert api.post(tc["t"]["mgr"], url, {"body": "x" * 2000}).status_code == 201
    assert api.get(tc["t"]["mgr"], "/tasks/987654/comments").status_code == 404
    assert api.post(tc["t"]["mgr"], "/tasks/987654/comments", {"body": "hi"}).status_code == 404


def test_people_outside_the_project_cannot_read_or_write(api, tc):
    url = f"/tasks/{tc['task']}/comments"
    assert api.get(tc["t"]["out"], url).status_code == 404                                        # the task does not exist for them
    assert api.post(tc["t"]["out"], url, {"body": "let me in"}).status_code == 404
    api.ensure_company("tccross")
    other = api.login("tccross", "founder@tccross.com")
    assert api.get(other, url).status_code == 404 and api.post(other, url, {"body": "x"}).status_code == 404


def test_the_other_party_is_notified_but_not_the_author(api, tc):
    api.post(tc["t"]["assignee"], f"/tasks/{tc['task']}/comments", {"body": "Question about the schema"})
    def got(tok):
        return [n for n in api.get(tok, "/notifications").json()["items"] if n["title"] == "New comment on a task" and "Question about the schema" in (n["body"] or "")]
    assert got(tc["t"]["mgr"]) and not got(tc["t"]["assignee"])


def test_who_may_delete(api, tc):
    url = f"/tasks/{tc['task']}/comments"
    mine = api.post(tc["t"]["member"], url, {"body": "delete me"}).json()["id"]
    theirs = api.post(tc["t"]["assignee"], url, {"body": "not yours"}).json()["id"]
    assert api.delete(tc["t"]["member"], f"{url}/{theirs}").status_code == 403                    # not your comment
    assert api.delete(tc["t"]["member"], f"{url}/{mine}").status_code == 204                      # your own
    assert api.delete(tc["t"]["mgr"], f"{url}/{theirs}").status_code == 204                       # the project owner moderates
    assert api.delete(tc["t"]["mgr"], f"{url}/{theirs}").status_code == 404
    assert api.delete(tc["t"]["out"], f"{url}/{mine}").status_code == 404


def test_comments_go_with_the_task(api, tc):
    p = api.post(tc["t"]["mgr"], "/projects", {"name": "Short lived"}).json()
    task = api.post(tc["t"]["mgr"], f"/projects/{p['id']}/tasks", {"title": "Temp"}).json()["id"]
    assert api.post(tc["t"]["mgr"], f"/tasks/{task}/comments", {"body": "bye"}).status_code == 201
    assert api.delete(tc["t"]["mgr"], f"/tasks/{task}").status_code == 204
    assert api.get(tc["t"]["mgr"], f"/tasks/{task}/comments").status_code == 404
