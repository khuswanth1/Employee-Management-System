"""Password reset and e-mail verification by link, and TOTP two-step verification."""
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import mailer, mfa
from app.core.security import decrypt
from app.db.base import utcnow
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import AuthToken, User
from app.main import app
from app.tenancy.manager import tenants
from tests.conftest import PW

WEB = {"X-WS-Client": "web"}
NEW_PW = "N3w-Strong-Pw-99"
V1 = "/api/v1"


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}) or True)
    return sent


@pytest.fixture
def clock(monkeypatch):
    """Moves the TOTP clock forward in 30 s steps so tests can sign in repeatedly without tripping the replay guard."""
    state = {"step": mfa.current_step()}
    monkeypatch.setattr(mfa, "current_step", lambda now=None: state["step"])

    class Clock:
        def code(self, secret):
            return mfa._code_at(secret, state["step"])

        def advance(self, n=1):
            state["step"] += n

    return Clock()


def _link_parts(mail):
    m = re.search(r"\?company=([a-z0-9-]+)&token=([\w-]+)", mail["body"])
    assert m, mail["body"]
    return m.group(1), m.group(2)


def _new_user(api, org, email, role="employee"):
    api.add_user(org["founder"], email, role)
    return api.login("acme", email)


def _tenant_db(slug):
    with platform_session() as pdb:
        company = pdb.scalar(select(Company).where(Company.slug == slug))
        pdb.expunge(company)
    return tenants.session_for(company)


def _login(api, email, password=PW, slug="acme"):
    return api.c.post(f"{V1}/auth/login", json={"company_slug": slug, "email": email, "password": password})


# ------------------------------------------------------------- password reset

def test_reset_flow_end_to_end(api, org, outbox):
    old = _new_user(api, org, "reset-a@acme.com")
    r = api.c.post(f"{V1}/auth/password-reset/request", json={"email": "Reset-A@acme.com", "company_slug": "acme"})
    assert r.status_code == 202
    assert [m["to"] for m in outbox] == ["reset-a@acme.com"]
    slug, token = _link_parts(outbox[0])
    assert slug == "acme" and "/reset-password" in outbox[0]["body"]

    done = api.c.post(f"{V1}/auth/password-reset/confirm", json={"company_slug": slug, "token": token, "new_password": NEW_PW})
    assert done.status_code == 204
    assert _login(api, "reset-a@acme.com").status_code == 401
    assert _login(api, "reset-a@acme.com", NEW_PW).status_code == 200
    assert api.get(old, "/auth/me").status_code == 401  # sessions from before the reset are gone
    again = api.c.post(f"{V1}/auth/password-reset/confirm", json={"company_slug": slug, "token": token, "new_password": "An0ther-Strong-1"})
    assert again.status_code == 400  # single use
    me = api.get(_login(api, "reset-a@acme.com", NEW_PW).json()["access_token"], "/auth/me").json()
    assert me["email_verified"] is True  # the link proved control of the mailbox


def test_unknown_and_known_addresses_get_the_same_answer(api, org, outbox):
    _new_user(api, org, "reset-b@acme.com")
    a = api.c.post(f"{V1}/auth/password-reset/request", json={"email": "reset-b@acme.com"})
    b = api.c.post(f"{V1}/auth/password-reset/request", json={"email": "nobody-here@acme.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert [m["to"] for m in outbox] == ["reset-b@acme.com"]


def test_reset_requests_are_rate_limited(api, org, outbox):
    codes = [api.c.post(f"{V1}/auth/password-reset/request", json={"email": "spam@acme.com"}).status_code for _ in range(6)]
    assert codes == [202] * 5 + [429]


def test_no_reset_mail_for_offboarded_accounts(api, org, outbox):
    _new_user(api, org, "reset-gone@acme.com")
    uid = api.get(api.login("acme", "reset-gone@acme.com"), "/auth/me").json()["id"]
    assert api.post(org["hr"], f"/employees/{uid}/offboard").status_code == 200
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "reset-gone@acme.com", "company_slug": "acme"})
    assert outbox == []


def test_bad_tokens_and_weak_passwords_are_refused(api, org, outbox):
    _new_user(api, org, "reset-c@acme.com")
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "reset-c@acme.com", "company_slug": "acme"})
    slug, token = _link_parts(outbox[0])
    url = f"{V1}/auth/password-reset/confirm"
    assert api.c.post(url, json={"company_slug": slug, "token": token, "new_password": "weak"}).status_code == 422
    assert api.c.post(url, json={"company_slug": slug, "token": "x" * 43, "new_password": NEW_PW}).status_code == 400
    assert api.c.post(url, json={"company_slug": "no-such-company", "token": token, "new_password": NEW_PW}).status_code == 400
    assert _login(api, "reset-c@acme.com").status_code == 200  # password untouched


def test_token_from_one_company_does_not_work_in_another(api, org, outbox):
    api.ensure_company("globex")
    _new_user(api, org, "reset-d@acme.com")
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "reset-d@acme.com", "company_slug": "acme"})
    _, token = _link_parts(outbox[0])
    r = api.c.post(f"{V1}/auth/password-reset/confirm", json={"company_slug": "globex", "token": token, "new_password": NEW_PW})
    assert r.status_code == 400


def test_expired_and_superseded_tokens_are_refused(api, org, outbox):
    _new_user(api, org, "reset-e@acme.com")
    req = {"email": "reset-e@acme.com", "company_slug": "acme"}
    api.c.post(f"{V1}/auth/password-reset/request", json=req)
    api.c.post(f"{V1}/auth/password-reset/request", json=req)
    (_, first), (_, second) = _link_parts(outbox[0]), _link_parts(outbox[1])
    url = f"{V1}/auth/password-reset/confirm"
    assert api.c.post(url, json={"company_slug": "acme", "token": first, "new_password": NEW_PW}).status_code == 400  # superseded
    with _tenant_db("acme") as db:
        for t in db.scalars(select(AuthToken).where(AuthToken.used_at.is_(None))):
            t.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert api.c.post(url, json={"company_slug": "acme", "token": second, "new_password": NEW_PW}).status_code == 400  # expired


def test_only_a_hash_of_the_token_is_stored(api, org, outbox):
    _new_user(api, org, "reset-f@acme.com")
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "reset-f@acme.com", "company_slug": "acme"})
    _, token = _link_parts(outbox[0])
    with _tenant_db("acme") as db:
        stored = [t.token_hash for t in db.scalars(select(AuthToken))]
    assert token not in stored and all(len(h) == 64 for h in stored)


# ------------------------------------------------------- e-mail verification

def test_email_verification_flow(api, org, outbox):
    tok = _new_user(api, org, "verify-a@acme.com")
    assert api.get(tok, "/auth/me").json()["email_verified"] is False
    assert api.post(tok, "/auth/verify-email/request").status_code == 202
    assert outbox[-1]["to"] == "verify-a@acme.com"
    assert api.post(tok, "/auth/verify-email/request").status_code == 429  # one per minute
    slug, token = _link_parts(outbox[-1])
    assert api.c.post(f"{V1}/auth/verify-email/confirm", json={"company_slug": slug, "token": "y" * 43}).status_code == 400
    assert api.c.post(f"{V1}/auth/verify-email/confirm", json={"company_slug": slug, "token": token}).status_code == 204
    assert api.get(tok, "/auth/me").json()["email_verified"] is True
    assert api.c.post(f"{V1}/auth/verify-email/confirm", json={"company_slug": slug, "token": token}).status_code == 400
    assert api.post(tok, "/auth/verify-email/request").status_code == 409


def test_a_reset_token_cannot_verify_an_email_and_vice_versa(api, org, outbox):
    tok = _new_user(api, org, "verify-b@acme.com")
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "verify-b@acme.com", "company_slug": "acme"})
    _, reset_token = _link_parts(outbox[-1])
    assert api.c.post(f"{V1}/auth/verify-email/confirm", json={"company_slug": "acme", "token": reset_token}).status_code == 400
    api.post(tok, "/auth/verify-email/request")
    _, verify_token = _link_parts(outbox[-1])
    r = api.c.post(f"{V1}/auth/password-reset/confirm", json={"company_slug": "acme", "token": verify_token, "new_password": NEW_PW})
    assert r.status_code == 400


# ------------------------------------------------------------------------ MFA

def _enrol(api, tok, clock):
    setup = api.post(tok, "/auth/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["secret"] in setup["otpauth_uri"]
    r = api.post(tok, "/auth/mfa/enable", {"code": clock.code(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def test_totp_matches_the_rfc6238_test_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    assert mfa._code_at(secret, 59 // 30) == "287082"  # RFC 6238 appendix B, T=59 (6 digits of 94287082)
    assert mfa.verify_totp(secret, "287082", now=59) == 1
    assert mfa.verify_totp(secret, "287082", last_step=1, now=59) is None  # replay
    assert mfa.verify_totp(secret, "000000", now=59) is None


def test_enrol_then_sign_in_needs_the_second_factor(api, org, clock):
    tok = _new_user(api, org, "mfa-a@acme.com")
    secret, recovery = _enrol(api, tok, clock)
    assert len(recovery) == 10
    me = api.get(tok, "/auth/me").json()
    assert me["mfa_enabled"] is True

    clock.advance()
    r = _login(api, "mfa-a@acme.com")
    body = r.json()
    assert r.status_code == 200 and body["mfa_required"] is True and body["mfa_token"] and not body.get("access_token")
    # the half-way token is not a session
    assert api.get(body["mfa_token"], "/auth/me").status_code == 401

    bad = api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": "000000"})
    assert bad.status_code == 400
    ok = api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": clock.code(secret)})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert api.get(ok.json()["access_token"], "/auth/me").status_code == 200
    # the mfa_token works once
    again = api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": clock.code(secret)})
    assert again.status_code == 401


def test_a_totp_code_cannot_be_replayed(api, org, clock):
    tok = _new_user(api, org, "mfa-b@acme.com")
    secret, _ = _enrol(api, tok, clock)
    clock.advance()
    code = clock.code(secret)
    t1 = _login(api, "mfa-b@acme.com").json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t1, "code": code}).status_code == 200
    t2 = _login(api, "mfa-b@acme.com").json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": code}).status_code == 400
    clock.advance()
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": clock.code(secret)}).status_code == 200


def test_recovery_codes_work_once(api, org, clock):
    tok = _new_user(api, org, "mfa-c@acme.com")
    _, recovery = _enrol(api, tok, clock)
    t1 = _login(api, "mfa-c@acme.com").json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t1, "code": recovery[0].upper()}).status_code == 200
    t2 = _login(api, "mfa-c@acme.com").json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": recovery[0]}).status_code == 400
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t2, "code": recovery[1]}).status_code == 200


def test_wrong_codes_lock_the_account_even_with_fresh_mfa_tokens(api, org, clock):
    tok = _new_user(api, org, "mfa-d@acme.com")
    secret, _ = _enrol(api, tok, clock)
    statuses = []
    for _ in range(7):
        t = _login(api, "mfa-d@acme.com").json()["mfa_token"]
        statuses.append(api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t, "code": "000000"}).status_code)
    assert statuses[:5] == [400] * 5 and statuses[5:] == [429, 429]
    clock.advance()
    t = _login(api, "mfa-d@acme.com").json()["mfa_token"]
    assert api.c.post(f"{V1}/auth/mfa/verify", json={"mfa_token": t, "code": clock.code(secret)}).status_code == 429  # even the right code


def test_enrolment_needs_a_valid_code_and_the_secret_is_stored_encrypted(api, org, clock):
    tok = _new_user(api, org, "mfa-e@acme.com")
    setup = api.post(tok, "/auth/mfa/setup").json()
    assert api.post(tok, "/auth/mfa/enable", {"code": "123456"}).status_code == 400
    assert api.get(tok, "/auth/me").json()["mfa_enabled"] is False
    assert _login(api, "mfa-e@acme.com").json().get("access_token")  # still plain password sign-in
    with _tenant_db("acme") as db:
        u = db.scalar(select(User).where(User.email == "mfa-e@acme.com"))
        assert u.mfa_secret_enc and setup["secret"] not in u.mfa_secret_enc and decrypt(u.mfa_secret_enc) == setup["secret"]
    api.post(tok, "/auth/mfa/enable", {"code": clock.code(setup["secret"])})
    assert api.post(tok, "/auth/mfa/setup").status_code == 409  # cannot re-enrol over a live secret
    with _tenant_db("acme") as db:
        u = db.scalar(select(User).where(User.email == "mfa-e@acme.com"))
        assert all(len(h) == 64 for h in u.mfa_recovery)


def test_disable_needs_password_and_code(api, org, clock):
    tok = _new_user(api, org, "mfa-f@acme.com")
    secret, _ = _enrol(api, tok, clock)
    clock.advance()
    assert api.post(tok, "/auth/mfa/disable", {"password": "wrong-Password-1", "code": clock.code(secret)}).status_code == 400
    assert api.post(tok, "/auth/mfa/disable", {"password": PW, "code": "000000"}).status_code == 400
    assert api.post(tok, "/auth/mfa/disable", {"password": PW, "code": clock.code(secret)}).status_code == 204
    assert _login(api, "mfa-f@acme.com").json().get("access_token")


def test_admin_can_reset_a_lost_second_factor(api, org, clock):
    tok = _new_user(api, org, "mfa-g@acme.com")
    _enrol(api, tok, clock)
    uid = api.get(tok, "/auth/me").json()["id"]
    assert api.post(org["emp"], f"/employees/{uid}/mfa/reset").status_code == 403
    assert api.post(org["hr"], f"/employees/{uid}/mfa/reset").status_code == 204
    assert api.get(tok, "/auth/me").status_code == 401  # sessions end with it
    assert _login(api, "mfa-g@acme.com").json().get("access_token")


def test_hr_cannot_reset_a_founders_second_factor(api, org, clock):
    f = org["founder"]
    _enrol(api, f, clock)
    fid = api.get(f, "/auth/me").json()["id"]
    assert api.post(org["hr"], f"/employees/{fid}/mfa/reset").status_code in (403, 404)
    api.post(f, "/auth/mfa/disable", {"password": PW, "code": "000000"})  # (wrong code: still on)
    assert api.get(f, "/auth/me").json()["mfa_enabled"] is True
    # tidy up so the shared founder keeps plain password sign-in for the other tests
    with _tenant_db("acme") as db:
        u = db.get(User, fid)
        u.mfa_enabled, u.mfa_secret_enc, u.mfa_last_step, u.mfa_recovery = False, None, None, None
        db.commit()


def test_password_reset_does_not_switch_mfa_off(api, org, outbox, clock):
    tok = _new_user(api, org, "mfa-h@acme.com")
    _enrol(api, tok, clock)
    api.c.post(f"{V1}/auth/password-reset/request", json={"email": "mfa-h@acme.com", "company_slug": "acme"})
    _, token = _link_parts(outbox[-1])
    api.c.post(f"{V1}/auth/password-reset/confirm", json={"company_slug": "acme", "token": token, "new_password": NEW_PW})
    r = _login(api, "mfa-h@acme.com", NEW_PW).json()
    assert r["mfa_required"] is True and not r.get("access_token")


def test_browser_sign_in_with_mfa_sets_cookies_only_after_the_second_step(api, org, clock):
    tok = _new_user(api, org, "mfa-i@acme.com")
    secret, _ = _enrol(api, tok, clock)
    clock.advance()
    with TestClient(app) as browser:
        r = browser.post(f"{V1}/auth/login", json={"email": "mfa-i@acme.com", "password": PW}, headers=WEB)
        assert r.json()["mfa_required"] is True and not r.headers.get_list("set-cookie")
        assert browser.get(f"{V1}/auth/me").status_code == 401
        ok = browser.post(f"{V1}/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": clock.code(secret)}, headers=WEB)
        assert ok.status_code == 200 and browser.get(f"{V1}/auth/me").json()["email"] == "mfa-i@acme.com"
