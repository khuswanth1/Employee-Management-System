"""Role-based access matrix."""
import pytest

from tests.conftest import PW


@pytest.mark.parametrize("key,expected", [("founder", 200), ("hr", 200), ("mgr", 200), ("emp", 403)])
def test_employee_list_roles(api, org, key, expected):
    assert api.get(org[key], "/employees").status_code == expected


def test_employee_role_gets_403_everywhere_privileged(api, org):
    emp = org["emp"]
    for method, url, body in [
        ("get", "/employees", None), ("post", "/employees", {"email": "a@b.com", "full_name": "A B", "password": PW}),
        ("post", "/departments", {"name": "Eng"}), ("post", "/projects", {"name": "Proj"}),
        ("get", "/admin/audit-logs", None), ("get", "/webhooks", None), ("get", "/leave/requests", None),
        ("get", "/attendance", None), ("get", "/reports/leave.csv", None), ("get", "/daily-updates/team", None),
        ("put", "/admin/settings/standard_work_hours", {"value": "9"}), ("post", "/leave/types", {"name": "Study", "annual_quota": 3}),
    ]:
        r = getattr(api, method)(emp, url, body) if body is not None else getattr(api, method)(emp, url)
        assert r.status_code == 403, (method, url, r.status_code)


def test_hr_cannot_grant_founder_or_touch_founder(api, org):
    r = api.post(org["hr"], "/employees", {"email": "evil@acme.com", "full_name": "Evil One", "password": PW, "role": "founder"})
    assert r.status_code == 403
    founder_id = api.get(org["founder"], "/auth/me").json()["id"]
    assert api.patch(org["hr"], f"/employees/{founder_id}", {"designation": "x"}).status_code == 403
    assert api.post(org["hr"], f"/employees/{founder_id}/reset-password", {"new_password": "Hacked-Pw1"}).status_code == 403
    assert api.post(org["hr"], f"/employees/{founder_id}/offboard").status_code == 403
    assert api.patch(org["hr"], f"/employees/{org['ids']['emp']}", {"role": "founder"}).status_code == 403


def test_last_founder_cannot_be_demoted_or_removed(api, org):
    fid = api.get(org["founder"], "/auth/me").json()["id"]
    assert api.patch(org["founder"], f"/employees/{fid}", {"role": "hr"}).status_code == 400
    assert api.post(org["founder"], f"/employees/{fid}/offboard").status_code == 400  # also can't offboard self


def test_employee_can_only_view_self_manager_views_reports(api, org):
    ids = org["ids"]
    assert api.get(org["emp"], f"/employees/{ids['emp']}").status_code == 200
    assert api.get(org["emp"], f"/employees/{ids['emp2']}").status_code == 403
    assert api.get(org["mgr"], f"/employees/{ids['emp']}").status_code == 200
    assert api.get(org["mgr2"], f"/employees/{ids['emp']}").status_code == 403  # not their report
    assert api.get(org["hr"], f"/employees/{ids['emp']}").status_code == 200


def test_directory_exposes_no_sensitive_fields(api, org):
    item = api.get(org["emp"], "/employees/directory").json()["items"][0]
    assert "phone" not in item and "password_hash" not in item and "hire_date" not in item


def test_mass_assignment_is_ignored(api, org):
    """Extra fields like is_active/password_hash in a body must not be applied."""
    r = api.patch(org["hr"], f"/employees/{org['ids']['emp2']}", {"designation": "Dev", "password_hash": "x", "is_active": False, "id": 999})
    assert r.status_code == 200
    body = r.json()
    assert body["is_active"] is True and body["id"] == org["ids"]["emp2"]
    assert api.get(org["emp2"], "/dashboard").status_code == 200


def test_manager_hierarchy_cycles_rejected(api, org):
    ids = org["ids"]
    api.make_company("cyc")
    f = api.login("cyc", "founder@cyc.com")
    a = api.add_user(f, "a@cyc.com", "manager")
    b = api.add_user(f, "b@cyc.com", "employee", manager_id=a["id"])
    assert api.patch(f, f"/employees/{a['id']}", {"manager_id": b["id"]}).status_code == 400
    assert api.patch(f, f"/employees/{a['id']}", {"manager_id": a["id"]}).status_code == 400


def test_only_founder_manages_webhooks_and_settings(api, org):
    assert api.get(org["hr"], "/webhooks").status_code == 403
    assert api.put(org["hr"], "/admin/settings/standard_work_hours", {"value": "7"}).status_code == 403
    assert api.get(org["founder"], "/webhooks").status_code == 200


def test_me_lists_a_managers_effective_permissions_so_the_ui_can_hide_refused_pages(api, org):
    from app.access import MANAGER_PERMISSIONS
    f = org["founder"]
    assert api.get(org["mgr"], "/auth/me").json()["permissions"] == sorted(MANAGER_PERMISSIONS)   # no explicit list = everything
    assert api.get(org["emp"], "/auth/me").json()["permissions"] is None
    assert api.get(f, "/auth/me").json()["permissions"] is None
    # a manager without attendance.approve is refused by the queue, exactly what the menu now hides
    mid = org["ids"]["mgr2"]
    assert api.patch(f, f"/managers/{mid}", {"permissions": ["leave.approve"]}).status_code == 200
    try:
        assert api.get(org["mgr2"], "/auth/me").json()["permissions"] == ["leave.approve"]
        assert api.get(org["mgr2"], "/attendance/corrections").status_code == 403
    finally:
        api.patch(f, f"/managers/{mid}", {"permissions": sorted(MANAGER_PERMISSIONS)})
