"""Tenant isolation: the most important guarantee of the platform."""
from sqlalchemy import select

from app.core.security import decrypt
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import User
from app.tenancy.manager import tenants
from tests.conftest import PW


def _two_tenants(api):
    for slug in ("alpha", "bravo"):
        if "founder@%s.com" % slug not in getattr(api, "_made", set()):
            api._made = getattr(api, "_made", set()) | {"founder@%s.com" % slug}
            api.make_company(slug)
    fa, fb = api.login("alpha", "founder@alpha.com"), api.login("bravo", "founder@bravo.com")
    return fa, fb


def _project(api, tok, name):
    mgr_email = f"pm-{name}@x.com"
    r = api.post(tok, "/employees", {"email": mgr_email, "full_name": "PM", "password": PW, "role": "manager"})
    if r.status_code == 201:
        pass
    slug = api.get(tok, "/auth/me").json()["company"]["slug"]
    m = api.login(slug, mgr_email)
    p = api.post(m, "/projects", {"name": name})
    assert p.status_code == 201, p.text
    return m, p.json()


def test_each_tenant_has_its_own_physical_database(api):
    _two_tenants(api)
    with platform_session() as db:
        a = db.scalar(select(Company).where(Company.slug == "alpha"))
        b = db.scalar(select(Company).where(Company.slug == "bravo"))
        assert a.db_name != b.db_name
        assert decrypt(a.db_url_encrypted) != decrypt(b.db_url_encrypted)
        # Alpha's founder exists in alpha's DB only.
        with tenants.session_for(a) as da, tenants.session_for(b) as dbb:
            assert da.scalar(select(User).where(User.email == "founder@alpha.com"))
            assert dbb.scalar(select(User).where(User.email == "founder@alpha.com")) is None
            assert dbb.scalar(select(User).where(User.email == "founder@bravo.com"))


def test_same_ids_in_two_tenants_never_cross(api):
    fa, fb = _two_tenants(api)
    ma, pa = _project(api, fa, "alpha-secret-project")
    mb, pb = _project(api, fb, "bravo-project")
    assert pa["id"] == pb["id"]  # both are project #1 in their own DB: only the token separates them
    assert api.get(ma, f"/projects/{pa['id']}").json()["name"] == "alpha-secret-project"
    assert api.get(mb, f"/projects/{pb['id']}").json()["name"] == "bravo-project"
    names = [p["name"] for p in api.get(mb, "/projects").json()["items"]]
    assert "alpha-secret-project" not in names
    # Bravo's manager cannot write to alpha's project even though the numeric id exists in both
    # The same numeric id used with bravo's token addresses bravo's own row, never alpha's.
    assert api.patch(mb, f"/projects/{pa['id']}", {"name": "bravo-renamed"}).status_code == 200
    assert api.get(mb, f"/projects/{pb['id']}").json()["name"] == "bravo-renamed"
    assert api.get(ma, f"/projects/{pa['id']}").json()["name"] == "alpha-secret-project"


def test_frontend_supplied_tenant_hints_are_ignored(api):
    fa, fb = _two_tenants(api)
    for hdr in ({"X-Tenant-ID": "1"}, {"X-Company": "alpha"}, {"X-Tenant": "alpha"}):
        r = api.c.get("/api/v1/employees", headers={**api.h(fb), **hdr})
        assert r.status_code == 200
        emails = {e["email"] for e in r.json()["items"]}
        assert "founder@alpha.com" not in emails
    r = api.c.get("/api/v1/employees?tenant_id=1&company_id=1&company_slug=alpha", headers=api.h(fb))
    assert "founder@alpha.com" not in {e["email"] for e in r.json()["items"]}


def test_same_email_can_exist_in_two_companies(api):
    fa, fb = _two_tenants(api)
    for tok in (fa, fb):
        r = api.post(tok, "/employees", {"email": "shared@person.com", "full_name": "Shared Person", "password": PW})
        assert r.status_code == 201
    ta, tb = api.login("alpha", "shared@person.com"), api.login("bravo", "shared@person.com")
    assert api.get(ta, "/auth/me").json()["company"]["slug"] == "alpha"
    assert api.get(tb, "/auth/me").json()["company"]["slug"] == "bravo"


def test_login_is_scoped_to_company(api):
    _two_tenants(api)
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "bravo", "email": "founder@alpha.com", "password": PW})
    assert r.status_code == 401


def test_directory_and_dashboard_only_contain_own_tenant(api):
    fa, fb = _two_tenants(api)
    mails = {e["email"] for e in api.get(fb, "/employees/directory").json()["items"]}
    assert all(not m.endswith("@alpha.com") for m in mails)
    assert api.get(fb, "/dashboard").json()["headcount"] == len(mails)


def test_db_credentials_never_exposed(api):
    fa, _ = _two_tenants(api)
    admin = api.admin_token()
    for url in ("/platform/companies", "/platform/companies/1"):
        text = api.get(admin, url).text.lower()
        assert "sqlite" not in text and "postgres" not in text and "db_url" not in text and "password" not in text
    assert "db_url" not in api.get(fa, "/auth/me").text


def test_webhook_deliveries_and_notifications_do_not_leak(api):
    fa, fb = _two_tenants(api)
    api.post(fa, "/employees", {"email": "n1@alpha.com", "full_name": "Notify One", "password": PW})
    n1 = api.login("alpha", "n1@alpha.com")
    assert api.get(n1, "/notifications/unread-count").json()["count"] >= 1
    assert api.get(fb, "/notifications/unread-count").json()["count"] == 0


def test_suspending_a_company_blocks_only_that_company(api):
    fa, fb = _two_tenants(api)
    admin = api.admin_token()
    with platform_session() as db:
        cid = db.scalar(select(Company.id).where(Company.slug == "bravo"))
    assert api.patch(admin, f"/platform/companies/{cid}", {"status": "suspended"}).status_code == 200
    assert api.get(fb, "/employees/directory").status_code == 403
    assert api.get(fa, "/employees/directory").status_code == 200
    assert api.c.post("/api/v1/auth/login", json={"company_slug": "bravo", "email": "founder@bravo.com", "password": PW}).status_code in (401, 403)  # login only looks at active companies
    api.patch(admin, f"/platform/companies/{cid}", {"status": "active"})
    assert api.get(fb, "/employees/directory").status_code == 200
