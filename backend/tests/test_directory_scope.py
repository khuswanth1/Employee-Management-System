"""The picker directory is not a company-wide address book: it follows the caller's branch and hides contact data from employees."""
import pytest


@pytest.fixture(scope="module")
def co(api):
    api.make_company("dirco")
    f = api.login("dirco", "founder@dirco.com")
    north = api.post(f, "/branches", {"name": "North", "code": "nor"}).json()
    south = api.post(f, "/branches", {"name": "South", "code": "sou"}).json()
    u = {}
    for key, role, br in [("hr_all", "hr", None), ("hr_n", "hr", north), ("mgr_n", "manager", north), ("mgr_s", "manager", south),
                          ("emp_n", "employee", north), ("emp_n2", "employee", north), ("emp_s", "employee", south)]:
        u[key] = api.add_user(f, f"{key}@dirco.com", role, **({"branch_id": br["id"]} if br else {}))
    board = api.post(f, "/board/members", {"email": "board@dirco.com", "full_name": "Board One", "password": "Str0ng-Pw-12"})
    assert board.status_code == 201, board.text
    return {"f": f, "u": u, "t": {k: api.login("dirco", f"{k}@dirco.com") for k in u}}


def ids(api, tok):
    return {x["id"] for x in api.get(tok, "/employees/directory").json()["items"]}


def test_founder_and_company_wide_hr_see_everyone(api, co):
    everyone = ids(api, co["f"])
    assert {v["id"] for v in co["u"].values()} <= everyone
    assert ids(api, co["t"]["hr_all"]) >= {v["id"] for v in co["u"].values()}
    assert any(x["role"] == "board_member" for x in api.get(co["f"], "/employees/directory").json()["items"])


@pytest.mark.parametrize("who", ["hr_n", "mgr_n", "emp_n"])
def test_branch_people_see_their_own_branch_and_the_unassigned_only(api, co, who):
    seen = api.get(co["t"][who], "/employees/directory").json()["items"]
    got = {x["id"] for x in seen}
    u = co["u"]
    assert {u["emp_n"]["id"], u["emp_n2"]["id"], u["mgr_n"]["id"], u["hr_n"]["id"]} <= got
    assert not got & {u["emp_s"]["id"], u["mgr_s"]["id"]}                       # the other branch is invisible
    assert all(x["role"] != "board_member" for x in seen)                       # and so are board members
    assert all(x["branch_id"] in (None, u["emp_n"]["branch_id"]) for x in seen)


def test_employees_get_no_contact_data_for_others(api, co):
    me = co["u"]["emp_n"]["id"]
    for x in api.get(co["t"]["emp_n"], "/employees/directory").json()["items"]:
        if x["id"] == me:
            assert x["email"] and x["employee_code"]
        else:
            assert x["email"] is None and x["employee_code"] is None, x
    assert all(x["email"] for x in api.get(co["t"]["mgr_n"], "/employees/directory").json()["items"])  # managers keep it: they administer these people


def test_board_members_still_have_no_access(api, co):
    board = api.login("dirco", "board@dirco.com")
    assert api.get(board, "/employees/directory").status_code == 403


def test_colleague_card_shows_directory_facts_only(api, co):
    u = co["u"]
    emp, peer, other_branch = co["t"]["emp_n"], u["emp_n2"], u["emp_s"]
    r = api.get(emp, f"/employees/{peer['id']}/card")
    assert r.status_code == 200
    card = r.json()
    assert card["full_name"] == peer["full_name"] and card["can_open"] is False
    assert card["email"] is None                                              # employees get no e-mail for colleagues
    for secret in ("phone", "password_hash", "salary", "documents", "history", "date_of_birth", "address"):
        assert secret not in card
    assert api.get(emp, f"/employees/{peer['id']}").status_code in (403, 404)  # the full record is still closed
    assert api.get(emp, f"/employees/{emp and u['emp_n']['id']}/card").json()["can_open"] is True
    assert api.get(emp, f"/employees/{other_branch['id']}/card").status_code == 404   # other branches stay invisible
    mgr_card = api.get(co["t"]["mgr_n"], f"/employees/{peer['id']}/card").json()
    assert mgr_card["email"] == peer["email"] and mgr_card["can_open"] is False       # not their direct report: card only
    hr_card = api.get(co["t"]["hr_n"], f"/employees/{peer['id']}/card").json()
    assert hr_card["email"] == peer["email"] and hr_card["can_open"] is True          # HR of the branch may open the record
    founder = api.get(co["f"], f"/employees/{other_branch['id']}/card")
    assert founder.status_code == 200 and founder.json()["can_open"] is True
    board = api.login("dirco", "board@dirco.com")
    assert api.get(board, f"/employees/{peer['id']}/card").status_code == 403
    assert api.get(emp, "/employees/987654/card").status_code == 404


def test_a_suspended_person_stays_reachable_for_their_administrators_only(api, co):
    target = co["u"]["emp_n"]
    assert api.post(co["f"], f"/employees/{target['id']}/lifecycle/suspend", {"reason": "review of access"}).status_code in (200, 201)
    try:
        assert api.get(co["t"]["hr_n"], f"/employees/{target['id']}/card").status_code == 200        # HR can still open them to reinstate
        assert api.get(co["t"]["emp_n2"], f"/employees/{target['id']}/card").status_code == 404      # colleagues no longer see them
    finally:
        api.post(co["f"], f"/employees/{target['id']}/lifecycle/reinstate", {})
