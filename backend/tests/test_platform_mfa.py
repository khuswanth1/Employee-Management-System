"""Two-step verification for platform administrators (the most privileged accounts)."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import decrypt, hash_password
from app.db.platform_models import PlatformUser
from app.db.session import platform_session
from app.main import app
from tests.test_account_security import clock  # noqa: F401  (fixture: steps the TOTP clock)

V1 = "/api/v1"
PW = "Admin-Pass-12345"
WEB = {"X-WS-Client": "web"}
_n = iter(range(1000))


@pytest.fixture
def admin(api):
    """A fresh platform administrator per test, so the shared bootstrap admin keeps plain password sign-in."""
    email = f"pmfa{next(_n)}@platform.com"
    with platform_session() as db:
        db.add(PlatformUser(email=email, full_name="Second Admin", password_hash=hash_password(PW)))
        db.commit()
    return email


def _login(api, email, via="platform"):
    url = f"{V1}/auth/platform/login" if via == "platform" else f"{V1}/auth/login"
    return api.c.post(url, json={"email": email, "password": PW})


def _enrol(api, tok, clock):
    setup = api.post(tok, "/auth/platform/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["secret"] in setup["otpauth_uri"]
    r = api.post(tok, "/auth/platform/mfa/enable", {"code": clock.code(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


@pytest.mark.parametrize("via", ["platform", "company-login"])
def test_sign_in_needs_the_second_factor(api, admin, clock, via):
    tok = _login(api, admin).json()["access_token"]
    secret, recovery = _enrol(api, tok, clock)
    assert len(recovery) == 10
    clock.advance()
    r = _login(api, admin, via).json()
    assert r["mfa_required"] is True and r["mfa_token"] and not r.get("access_token") and not r.get("refresh_token")
    assert api.get(r["mfa_token"], "/platform/companies").status_code == 401  # half-way token is not a session
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "code": "000000"}).status_code == 400
    ok = api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "code": clock.code(secret)})
    assert ok.status_code == 200 and ok.json()["role"] == "platform_admin"
    assert api.get(ok.json()["access_token"], "/platform/companies").status_code == 200
    # one use only
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": r["mfa_token"], "code": clock.code(secret)}).status_code == 401


def test_other_admins_and_company_users_are_unaffected(api, admin, clock, org):
    tok = _login(api, admin).json()["access_token"]
    _enrol(api, tok, clock)
    assert api.c.post(f"{V1}/auth/platform/login", json={"email": "admin@platform.com", "password": "Platform-Admin-1"}).json().get("access_token")
    assert api.login("acme", "founder@acme.com")


def test_company_user_tokens_cannot_use_the_platform_mfa_endpoints(api, org):
    for path in ("setup",):
        assert api.post(org["founder"], f"/auth/platform/mfa/{path}").status_code == 403
    assert api.post(org["founder"], "/auth/platform/mfa/enable", {"code": "123456"}).status_code == 403


def test_codes_cannot_be_replayed_and_recovery_codes_work_once(api, admin, clock):
    tok = _login(api, admin).json()["access_token"]
    secret, recovery = _enrol(api, tok, clock)
    clock.advance()
    code = clock.code(secret)
    t1 = _login(api, admin).json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t1, "code": code}).status_code == 200
    t2 = _login(api, admin).json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": code}).status_code == 400
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": recovery[0]}).status_code == 200
    t3 = _login(api, admin).json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t3, "code": recovery[0]}).status_code == 400


def test_wrong_codes_lock_out_even_with_fresh_tokens(api, admin, clock):
    tok = _login(api, admin).json()["access_token"]
    secret, _ = _enrol(api, tok, clock)
    out = []
    for _ in range(7):
        t = _login(api, admin).json()["mfa_token"]
        out.append(api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t, "code": "000000"}).status_code)
    assert out[:5] == [400] * 5 and out[5:] == [429, 429]
    clock.advance()
    t = _login(api, admin).json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t, "code": clock.code(secret)}).status_code == 429


def test_enrolment_rules_and_encrypted_secret(api, admin, clock):
    tok = _login(api, admin).json()["access_token"]
    setup = api.post(tok, "/auth/platform/mfa/setup").json()
    assert api.post(tok, "/auth/platform/mfa/enable", {"code": "123456"}).status_code == 400
    assert _login(api, admin).json().get("access_token")  # not enabled yet: still password only
    with platform_session() as db:
        a = db.query(PlatformUser).filter_by(email=admin).one()
        assert setup["secret"] not in a.mfa_secret_enc and decrypt(a.mfa_secret_enc) == setup["secret"]
    api.post(tok, "/auth/platform/mfa/enable", {"code": clock.code(setup["secret"])})
    assert api.post(tok, "/auth/platform/mfa/setup").status_code == 409
    assert api.post(tok, "/auth/platform/mfa/enable", {"code": clock.code(setup["secret"])}).status_code == 409
    assert api.get(tok, "/auth/session").json()["mfa_enabled"] is True


def test_disable_needs_password_and_code_and_ends_other_sessions(api, admin, clock):
    tok = _login(api, admin).json()["access_token"]
    other = _login(api, admin).json()["access_token"]
    secret, _ = _enrol(api, tok, clock)
    clock.advance()
    assert api.post(tok, "/auth/platform/mfa/disable", {"password": "wrong", "code": clock.code(secret)}).status_code == 400
    assert api.post(tok, "/auth/platform/mfa/disable", {"password": PW, "code": "000000"}).status_code == 400
    assert api.post(tok, "/auth/platform/mfa/disable", {"password": PW, "code": clock.code(secret)}).status_code == 204
    assert api.get(other, "/platform/companies").status_code == 401
    assert _login(api, admin).json().get("access_token")


def test_browser_flow_sets_cookies_only_after_the_second_step(api, admin, clock):
    tok = _login(api, admin).json()["access_token"]
    secret, _ = _enrol(api, tok, clock)
    clock.advance()
    with TestClient(app) as browser:
        r = browser.post(f"{V1}/auth/login", json={"email": admin, "password": PW}, headers=WEB)
        assert r.json()["mfa_required"] is True and not r.headers.get_list("set-cookie")
        assert browser.get(f"{V1}/platform/companies").status_code == 401
        ok = browser.post(f"{V1}/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": clock.code(secret)}, headers=WEB)
        assert ok.status_code == 200 and browser.get(f"{V1}/platform/companies").status_code == 200


def test_break_glass_script_switches_it_off(api, admin, clock):
    import importlib.util
    from pathlib import Path

    tok = _login(api, admin).json()["access_token"]
    _enrol(api, tok, clock)
    spec = importlib.util.spec_from_file_location("reset_platform_mfa", Path(__file__).resolve().parent.parent / "scripts" / "reset_platform_mfa.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main("nobody@nowhere.com") == 1
    assert mod.main(admin.upper()) == 0
    assert api.get(tok, "/platform/companies").status_code == 401  # sessions ended
    assert _login(api, admin).json().get("access_token")  # password only again
