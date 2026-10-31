"""Server-side session revocation: logout, refresh rotation, password change/reset, sign out everywhere."""
import logging

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PW

WEB = {"X-WS-Client": "web"}
NEW_PW = "N3w-Strong-Pw-99"
ADMIN_LOGIN = {"email": "admin@platform.com", "password": "Platform-Admin-1"}


def _login(client, slug, email, password=PW):
    r = client.post("/api/v1/auth/login", json={"company_slug": slug, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _user(api, org, email):
    api.add_user(org["founder"], email, "employee")
    return email


def test_logout_revokes_the_tokens_server_side(api, org):
    _user(api, org, "rev-logout@acme.com")
    t = _login(api.c, "acme", "rev-logout@acme.com")
    assert api.get(t["access_token"], "/auth/me").status_code == 200
    assert api.c.post("/api/v1/auth/logout", headers=api.h(t["access_token"]), json={"refresh_token": t["refresh_token"]}).status_code == 204
    # a copied token must be dead even though the attacker never "cleared a cookie"
    assert api.get(t["access_token"], "/auth/me").status_code == 401
    assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_logout_only_ends_that_session(api, org):
    _user(api, org, "rev-two@acme.com")
    a = _login(api.c, "acme", "rev-two@acme.com")
    b = _login(api.c, "acme", "rev-two@acme.com")
    api.c.post("/api/v1/auth/logout", headers=api.h(a["access_token"]))
    assert api.get(a["access_token"], "/auth/me").status_code == 401
    assert api.get(b["access_token"], "/auth/me").status_code == 200


def test_cookie_logout_revokes_a_copied_cookie(api, org):
    _user(api, org, "rev-cookie@acme.com")
    with TestClient(app) as browser:
        r = browser.post("/api/v1/auth/login", json={"email": "rev-cookie@acme.com", "password": PW}, headers=WEB)
        assert r.status_code == 200
        access, refresh, device = (browser.cookies.get(n) for n in ("ws_access", "ws_refresh", "ws_device"))
        assert browser.post("/api/v1/auth/logout", headers=WEB).status_code == 204
        # an attacker who copied all three cookies before the user signed out
        with TestClient(app) as thief:
            for n, v in (("ws_access", access), ("ws_refresh", refresh), ("ws_device", device)):
                thief.cookies.set(n, v)
            assert thief.get("/api/v1/auth/me").status_code == 401
            assert thief.post("/api/v1/auth/refresh", headers=WEB).status_code == 401


def test_refresh_tokens_rotate_and_cannot_be_replayed(api, org):
    _user(api, org, "rev-rotate@acme.com")
    t = _login(api.c, "acme", "rev-rotate@acme.com")
    r = api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    assert api.get(r.json()["access_token"], "/auth/me").status_code == 200
    assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_an_access_token_cannot_be_used_as_a_refresh_token(api, org):
    _user(api, org, "rev-typ@acme.com")
    t = _login(api.c, "acme", "rev-typ@acme.com")
    assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401


def test_change_password_signs_out_other_sessions(api, org):
    _user(api, org, "rev-pw@acme.com")
    a = _login(api.c, "acme", "rev-pw@acme.com")
    b = _login(api.c, "acme", "rev-pw@acme.com")
    r = api.post(a["access_token"], "/auth/change-password", {"current_password": PW, "new_password": NEW_PW})
    assert r.status_code == 204
    for t in (a, b):  # API clients sign in again; the old refresh tokens are dead too
        assert api.get(t["access_token"], "/auth/me").status_code == 401
        assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert api.get(_login(api.c, "acme", "rev-pw@acme.com", NEW_PW)["access_token"], "/auth/me").status_code == 200


def test_change_password_keeps_the_current_browser_signed_in(api, org):
    _user(api, org, "rev-pw-web@acme.com")
    with TestClient(app) as browser, TestClient(app) as other:
        for c in (browser, other):
            assert c.post("/api/v1/auth/login", json={"email": "rev-pw-web@acme.com", "password": PW}, headers=WEB).status_code == 200
        r = browser.post("/api/v1/auth/change-password", json={"current_password": PW, "new_password": NEW_PW}, headers=WEB)
        assert r.status_code == 204
        assert browser.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401


def test_admin_password_reset_signs_the_employee_out(api, org):
    _user(api, org, "rev-reset@acme.com")
    t = _login(api.c, "acme", "rev-reset@acme.com")
    uid = api.get(t["access_token"], "/auth/me").json()["id"]
    assert api.post(org["hr"], f"/employees/{uid}/reset-password", {"new_password": "Temp1234"}).status_code == 204
    assert api.get(t["access_token"], "/auth/me").status_code == 401
    assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_logout_all_signs_out_every_device(api, org):
    _user(api, org, "rev-all@acme.com")
    a = _login(api.c, "acme", "rev-all@acme.com")
    b = _login(api.c, "acme", "rev-all@acme.com")
    assert api.post(a["access_token"], "/auth/logout-all").status_code == 204
    assert api.get(a["access_token"], "/auth/me").status_code == 401
    assert api.get(b["access_token"], "/auth/me").status_code == 401
    assert api.get(_login(api.c, "acme", "rev-all@acme.com")["access_token"], "/auth/me").status_code == 200


def test_logout_all_does_not_touch_other_users_or_tenants(api, org):
    _user(api, org, "rev-iso@acme.com")
    api.ensure_company("globex")
    mine = _login(api.c, "acme", "rev-iso@acme.com")
    other_tenant = api.login("globex", "founder@globex.com")
    api.post(mine["access_token"], "/auth/logout-all")
    assert api.get(other_tenant, "/auth/me").status_code == 200
    assert api.get(org["founder"], "/auth/me").status_code == 200


def test_platform_admin_logout_and_logout_all(api):
    def sign_in():
        return api.c.post("/api/v1/auth/platform/login", json=ADMIN_LOGIN).json()["access_token"]

    tok = sign_in()
    assert api.get(tok, "/platform/companies").status_code == 200
    api.c.post("/api/v1/auth/logout", headers=api.h(tok))
    assert api.get(tok, "/platform/companies").status_code == 401
    tok2, tok3 = sign_in(), sign_in()
    assert api.post(tok2, "/auth/platform/logout-all").status_code == 204
    assert api.get(tok2, "/platform/companies").status_code == 401
    assert api.get(tok3, "/platform/companies").status_code == 401
    api._admin_token = None  # the cached admin token (if any) is gone as well


def test_sign_in_logs_do_not_contain_email_addresses(api, org):
    seen: list[str] = []

    class Grab(logging.Handler):  # pytest's logging plugin is disabled for this suite, so attach our own
        def emit(self, record):
            seen.append(record.getMessage() + " " + str(record.__dict__))

    h, root = Grab(level=logging.DEBUG), logging.getLogger("worksphere")
    old_level = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "ghost-user@acme.com", "password": "Wrong-Pass-1"})
        _login(api.c, "acme", "founder@acme.com")
    finally:
        root.removeHandler(h)
        root.setLevel(old_level)
    text = " | ".join(seen)
    assert "Login failed" in text and "signed in" in text  # the lines were captured at all
    assert "ghost-user@acme.com" not in text and "founder@acme.com" not in text
