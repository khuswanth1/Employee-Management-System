"""Extended employee profile: validation, restricted-field visibility, document verification and list sorting."""
from datetime import date, timedelta

import pytest

from tests.conftest import PW
from app.db.base import utcnow

P = "/employees/{}/profile"


@pytest.fixture(scope="module")
def prof(api, org):
    """Fresh people so changes here never leak into the shared `org` fixtures."""
    f = org["founder"]
    emp = api.add_user(f, "prof.emp@acme.com", "employee", manager_id=org["ids"]["mgr"], hire_date="2024-01-15")
    other = api.add_user(f, "prof.other@acme.com", "employee")
    return {"emp": emp["id"], "other": other["id"], "emp_tok": api.login("acme", "prof.emp@acme.com"), "other_tok": api.login("acme", "prof.other@acme.com")}


def test_empty_profile_has_defaults(api, org, prof):
    r = api.get(org["hr"], P.format(prof["emp"]))
    assert r.status_code == 200
    body = r.json()
    assert body["skills"] == [] and body["employment_type"] is None
    assert body["can_view_restricted"] is True and "personal_email" in body


def test_hr_sets_employment_details(api, org, prof):
    r = api.patch(org["hr"], P.format(prof["emp"]), {
        "employment_type": "full_time", "job_level": "L3", "probation_end_date": "2024-07-15", "confirmation_date": "2024-07-20",
        "notice_period_days": 30, "tags": ["remote", "Remote", " mentor "], "skills": ["Python", "SQL"],
    })
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["employment_type"] == "full_time" and b["notice_period_days"] == 30
    assert b["tags"] == ["remote", "mentor"], "duplicates (case-insensitive) and padding are removed"


@pytest.mark.parametrize("payload", [
    {"employment_type": "slave"}, {"notice_period_days": -1}, {"notice_period_days": 400},
    {"date_of_birth": "2999-01-01"}, {"date_of_birth": (utcnow().date() - timedelta(days=365 * 5)).isoformat()},
    {"personal_email": "not-an-email"}, {"emergency_contact_phone": "call me"}, {"gender": "x" * 5},
    {"skills": ["a" * 61]}, {"middle_name": "x" * 101},
])
def test_invalid_values_rejected(api, org, prof, payload):
    assert api.patch(org["hr"], P.format(prof["emp"]), payload).status_code == 422


def test_dates_must_follow_joining_date(api, org, prof):
    r = api.patch(org["hr"], P.format(prof["emp"]), {"probation_end_date": "2023-12-31"})
    assert r.status_code == 400 and "joining date" in r.json()["error"]["message"]
    r = api.patch(org["hr"], P.format(prof["emp"]), {"probation_end_date": "2024-08-01", "confirmation_date": "2024-07-01"})
    assert r.status_code == 400


def test_restricted_fields_hidden_from_manager_and_peers(api, org, prof):
    api.patch(org["hr"], P.format(prof["emp"]), {"personal_email": "private@example.com", "emergency_contact_name": "Jane", "emergency_contact_phone": "+1 555 0100"})
    own = api.get(prof["emp_tok"], P.format(prof["emp"])).json()
    assert own["personal_email"] == "private@example.com"
    mgr = api.get(org["mgr"], P.format(prof["emp"]))
    assert mgr.status_code == 200
    assert "personal_email" not in mgr.json() and "emergency_contact_name" not in mgr.json() and "date_of_birth" not in mgr.json()
    assert "private@example.com" not in mgr.text
    assert api.get(prof["other_tok"], P.format(prof["emp"])).status_code == 403


def test_employee_edits_own_personal_data_not_employment(api, org, prof):
    ok = api.patch(prof["emp_tok"], P.format(prof["emp"]), {"address": "1 Main St", "skills": ["Go"], "display_name": "Pat"})
    assert ok.status_code == 200 and ok.json()["address"] == "1 Main St"
    bad = api.patch(prof["emp_tok"], P.format(prof["emp"]), {"employment_type": "contract"})
    assert bad.status_code == 403
    assert api.patch(prof["other_tok"], P.format(prof["emp"]), {"skills": ["x"]}).status_code == 403


def test_manager_can_edit_employment_but_not_restricted(api, org, prof):
    assert api.patch(org["mgr"], P.format(prof["emp"]), {"job_level": "L4"}).status_code == 200
    assert api.patch(org["mgr"], P.format(prof["emp"]), {"address": "nope"}).status_code == 403
    assert api.patch(org["mgr2"], P.format(prof["emp"]), {"job_level": "L9"}).status_code == 403


def test_cross_tenant_profile_is_not_reachable(api, org, prof):
    api.ensure_company("globex")
    g = api.login("globex", "founder@globex.com")
    assert api.get(g, P.format(prof["emp"])).status_code in (403, 404)


def test_audit_records_field_names_never_values(api, org, prof):
    api.patch(org["hr"], P.format(prof["emp"]), {"personal_email": "audit-secret@example.com"})
    r = api.get(org["founder"], "/admin/audit-logs", params={"action": "employee.profile_updated", "page_size": 100})
    assert r.status_code == 200
    assert "employee.profile_updated" in r.text and "audit-secret@example.com" not in r.text


def test_document_type_expiry_and_verification(api, org, prof):
    url = f"/api/v1/employees/{prof['emp']}/documents"
    soon = (utcnow().date() + timedelta(days=10)).isoformat()
    up = api.c.post(url, headers=api.h(prof["emp_tok"]), files={"file": ("cert.pdf", b"%PDF-1.4 x", "application/pdf")}, data={"doc_type": "certification", "expiry_date": soon})
    assert up.status_code == 201, up.text
    doc = up.json()
    assert doc["verification_status"] == "pending" and doc["expires_soon"] is True and doc["is_expired"] is False
    bad_type = api.c.post(url, headers=api.h(prof["emp_tok"]), files={"file": ("a.pdf", b"%PDF", "application/pdf")}, data={"doc_type": "bogus"})
    assert bad_type.status_code == 400
    bad_date = api.c.post(url, headers=api.h(prof["emp_tok"]), files={"file": ("a.pdf", b"%PDF", "application/pdf")}, data={"expiry_date": "31/12/2030"})
    assert bad_date.status_code == 400
    # the owner cannot verify their own document, a peer cannot even see it, HR can
    assert api.patch(prof["emp_tok"], f"/documents/{doc['id']}/verification", {"status": "verified"}).status_code == 403
    assert api.patch(prof["other_tok"], f"/documents/{doc['id']}/verification", {"status": "verified"}).status_code == 403
    ok = api.patch(org["hr"], f"/documents/{doc['id']}/verification", {"status": "verified"})
    assert ok.status_code == 200 and ok.json()["verification_status"] == "verified" and ok.json()["verified_at"]
    assert api.patch(org["hr"], f"/documents/{doc['id']}/verification", {"status": "maybe"}).status_code == 422


def test_employee_list_sorting(api, org):
    asc = [e["full_name"] for e in api.get(org["hr"], "/employees", params={"sort": "full_name", "order": "asc", "page_size": 100}).json()["items"]]
    desc = [e["full_name"] for e in api.get(org["hr"], "/employees", params={"sort": "full_name", "order": "desc", "page_size": 100}).json()["items"]]
    assert asc == sorted(asc, key=str.lower) or asc == sorted(asc)
    assert desc == list(reversed(asc))
    assert api.get(org["hr"], "/employees", params={"sort": "password_hash"}).status_code == 422
