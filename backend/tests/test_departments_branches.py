"""Department and branch detail fields: validation, hierarchy rules, manager/HR representative rules, access."""
import pytest

D, B = "/departments", "/branches"


def msg(r):
    return r.json()["error"]["message"]


@pytest.fixture(scope="module")
def people(api, org):
    f = org["founder"]
    mgr = api.add_user(f, "dept.mgr@acme.com", "manager")
    hr = api.add_user(f, "dept.hr@acme.com", "hr")
    emp = api.add_user(f, "dept.emp@acme.com", "employee")
    return {"mgr": mgr["id"], "hr": hr["id"], "emp": emp["id"]}


# ---- departments ----------------------------------------------------------------------------------

def test_create_department_with_details(api, org, people):
    r = api.post(org["hr"], D, {"name": "Platform Eng", "code": "plat-1", "head_id": people["mgr"], "cost_center": "CC-100", "description": "  Core  "})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["code"] == "PLAT-1" and d["status"] == "active" and d["head_name"] and d["description"] == "Core"
    listed = [x for x in api.get(org["emp"], D).json()["items"] if x["id"] == d["id"]][0]
    assert listed["employee_count"] == 0, "count is calculated, never accepted from the client"


def test_department_code_and_name_unique(api, org):
    api.post(org["hr"], D, {"name": "Unique A", "code": "UNQ"})
    assert api.post(org["hr"], D, {"name": "Other", "code": "unq"}).status_code == 409
    assert api.post(org["hr"], D, {"name": "unique a"}).status_code == 409


@pytest.mark.parametrize("payload", [{"name": "X1", "code": "a b"}, {"name": "X2", "code": "!"}, {"name": "X3", "status": "gone"}, {"name": "A"}])
def test_department_invalid_input(api, org, payload):
    assert api.post(org["hr"], D, payload).status_code == 422


def test_department_head_must_be_real_active_person(api, org):
    assert api.post(org["hr"], D, {"name": "Ghost Head", "head_id": 999999}).status_code == 400


def test_department_hierarchy_and_cycles(api, org):
    a = api.post(org["hr"], D, {"name": "Tree A"}).json()
    b = api.post(org["hr"], D, {"name": "Tree B", "parent_id": a["id"]}).json()
    c = api.post(org["hr"], D, {"name": "Tree C", "parent_id": b["id"]}).json()
    assert c["parent_name"] == "Tree B"
    assert api.patch(org["hr"], f"{D}/{a['id']}", {"parent_id": c["id"]}).status_code == 400, "grandchild cannot be a parent"
    assert api.patch(org["hr"], f"{D}/{a['id']}", {"parent_id": a["id"]}).status_code == 400, "not its own parent"
    assert api.delete(org["hr"], f"{D}/{a['id']}").status_code == 409, "has sub-departments"
    assert api.delete(org["hr"], f"{D}/{c['id']}").status_code == 204


def test_partial_update_keeps_other_fields(api, org):
    d = api.post(org["hr"], D, {"name": "Partial", "code": "PRT", "cost_center": "CC-9"}).json()
    r = api.patch(org["hr"], f"{D}/{d['id']}", {"description": "now described"})
    assert r.status_code == 200 and r.json()["code"] == "PRT" and r.json()["cost_center"] == "CC-9"


def test_inactive_department_cannot_receive_people(api, org, people):
    d = api.post(org["hr"], D, {"name": "Frozen"}).json()
    api.patch(org["hr"], f"{D}/{d['id']}", {"status": "inactive"})
    r = api.patch(org["hr"], f"/employees/{people['emp']}", {"department_id": d["id"]})
    assert r.status_code == 400 and "inactive" in msg(r)


def test_only_hr_or_founder_edit_departments(api, org):
    assert api.post(org["emp"], D, {"name": "Nope"}).status_code == 403
    assert api.post(org["mgr"], D, {"name": "Nope"}).status_code == 403


def test_departments_are_tenant_scoped(api, org):
    api.ensure_company("globex")
    g = api.login("globex", "founder@globex.com")
    assert "Platform Eng" not in [d["name"] for d in api.get(g, D).json()["items"]]


# ---- branches -------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def branch(api, org, people):
    f = org["founder"]
    r = api.post(f, B, {"name": "Pune Office", "code": "pun", "city": "Pune", "state": "MH", "postal_code": "411001", "country": "India",
                        "contact_email": "pune@acme.com", "contact_phone": "+91 20 5550 100", "timezone": "Asia/Kolkata", "working_days": ["fri", "mon", "tue", "wed", "thu"]})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    api.post(f, f"{B}/{bid}/members", {"user_ids": [people["mgr"], people["hr"], people["emp"]]})
    return bid


def test_branch_details_roundtrip(api, org, branch):
    b = api.get(org["founder"], f"{B}/{branch}").json()
    assert b["timezone"] == "Asia/Kolkata" and b["working_days"] == ["mon", "tue", "wed", "thu", "fri"] and b["code"] == "PUN"
    assert b["contact_email"] == "pune@acme.com" and b["state"] == "MH"


@pytest.mark.parametrize("payload", [
    {"timezone": "Mars/Base"}, {"working_days": []}, {"working_days": ["mon", "mon"]}, {"working_days": ["funday"]},
    {"contact_email": "nope"}, {"contact_phone": "call me"}, {"postal_code": "x" * 21},
])
def test_branch_invalid_input(api, org, branch, payload):
    assert api.patch(org["founder"], f"{B}/{branch}", payload).status_code == 422


def test_branch_manager_and_hr_rep_rules(api, org, branch, people):
    f = org["founder"]
    ok = api.patch(f, f"{B}/{branch}", {"manager_id": people["mgr"], "hr_representative_id": people["hr"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["manager_name"] and ok.json()["hr_representative_name"]
    assert api.patch(f, f"{B}/{branch}", {"manager_id": people["emp"]}).status_code == 400, "employees cannot manage a branch"
    assert api.patch(f, f"{B}/{branch}", {"hr_representative_id": people["mgr"]}).status_code == 400, "representative must be HR"
    outsider = org["ids"]["mgr"]  # a manager who is not in this branch
    assert api.patch(f, f"{B}/{branch}", {"manager_id": outsider}).status_code == 400


def test_branch_manager_cleared_when_they_leave(api, org, branch, people):
    f = org["founder"]
    assert api.delete(f, f"{B}/{branch}/members/{people['mgr']}").status_code == 204
    b = api.get(f, f"{B}/{branch}").json()
    assert b["manager_id"] is None and b["hr_representative_id"] == people["hr"]


def test_new_branch_cannot_name_people_before_assignment(api, org, people):
    r = api.post(org["founder"], B, {"name": "Empty Office", "code": "EMP-O", "manager_id": people["hr"]})
    assert r.status_code == 400


def test_only_founder_edits_branches(api, org, branch):
    assert api.patch(org["hr"], f"{B}/{branch}", {"timezone": "UTC"}).status_code == 403
