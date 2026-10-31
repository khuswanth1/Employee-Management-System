import jwt

from app.core.config import get_settings
from app.core.ratelimit import login_limiter
from app.core.security import create_token, hash_password, verify_password
from tests.conftest import PW


def test_password_hashing_roundtrip_and_long_passwords():
    h = hash_password(PW)
    assert h != PW and verify_password(PW, h) and not verify_password("wrong", h)
    long_a, long_b = "A1" + "x" * 100 + "a", "A1" + "x" * 100 + "b"  # differ only after bcrypt's 72-byte limit
    assert not verify_password(long_b, hash_password(long_a))


def test_login_success_and_me(api, org):
    me = api.get(org["founder"], "/auth/me").json()
    assert me["role"] == "founder" and me["company"]["slug"] == "acme"
    assert "password" not in str(me).lower()


def test_login_failures_are_generic(api, org):
    bad_pw = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "founder@acme.com", "password": "nope"})
    bad_user = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "ghost@acme.com", "password": PW})
    bad_co = api.c.post("/api/v1/auth/login", json={"company_slug": "ghost", "email": "founder@acme.com", "password": PW})
    assert bad_pw.status_code == bad_user.status_code == bad_co.status_code == 401
    assert bad_pw.json() == bad_user.json() == bad_co.json()


def test_login_rate_limit(api, org):
    for _ in range(5):
        api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "emp2@acme.com", "password": "bad"})
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "emp2@acme.com", "password": PW})
    assert r.status_code == 429


def test_missing_and_garbage_tokens_rejected(api, org):
    assert api.c.get("/api/v1/dashboard").status_code == 401
    assert api.c.get("/api/v1/dashboard", headers={"Authorization": "Bearer garbage"}).status_code == 401
    tampered = org["emp"][:-3] + ("AAA" if not org["emp"].endswith("AAA") else "BBB")
    assert api.get(tampered, "/dashboard").status_code == 401


def test_token_signed_with_other_key_or_alg_none_rejected(api, org):
    forged = jwt.encode({"sub": "1", "role": "founder", "tid": 1, "typ": "access", "iss": "worksphere", "exp": 9999999999}, "x" * 40, algorithm="HS256")
    assert api.get(forged, "/dashboard").status_code == 401
    unsigned = jwt.encode({"sub": "1", "role": "founder", "tid": 1, "typ": "access", "iss": "worksphere", "exp": 9999999999}, None, algorithm="none")
    assert api.get(unsigned, "/dashboard").status_code == 401


def test_expired_token_and_refresh_token_cannot_be_used_as_access(api, org):
    expired = jwt.encode({"sub": "1", "role": "founder", "tid": 1, "typ": "access", "iss": "worksphere", "exp": 1}, get_settings().secret_key, algorithm="HS256")
    assert api.get(expired, "/dashboard").status_code == 401
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "emp@acme.com", "password": PW}).json()
    assert api.get(r["refresh_token"], "/dashboard").status_code == 401


def test_refresh_flow(api, org):
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": "emp@acme.com", "password": PW}).json()
    r2 = api.c.post("/api/v1/auth/refresh", json={"refresh_token": r["refresh_token"]})
    assert r2.status_code == 200
    assert api.get(r2.json()["access_token"], "/dashboard").status_code == 200
    assert api.c.post("/api/v1/auth/refresh", json={"refresh_token": r["access_token"]}).status_code == 401


def test_platform_and_tenant_tokens_are_not_interchangeable(api, org):
    assert api.get(org["founder"], "/platform/companies").status_code == 403
    assert api.get(api.admin_token(), "/dashboard").status_code == 401
    assert api.get(api.admin_token(), "/employees/directory").status_code == 401
    # a token minted for a role claim 'platform_admin' with tid is rejected too
    t = create_token(sub=1, role="platform_admin", tenant_id=1)
    assert api.get(t, "/dashboard").status_code == 401


def test_role_comes_from_database_not_token(api, org):
    api.make_company("rolechg")
    f = api.login("rolechg", "founder@rolechg.com")
    u = api.add_user(f, "x@rolechg.com", "hr")
    tok = api.login("rolechg", "x@rolechg.com")
    assert api.get(tok, "/employees").status_code == 200
    assert api.patch(f, f"/employees/{u['id']}", {"role": "employee"}).status_code == 200
    assert api.get(tok, "/employees").status_code == 403  # demotion is immediate, old token notwithstanding


def test_offboarded_user_token_stops_working(api):
    api.make_company("offb")
    f = api.login("offb", "founder@offb.com")
    u = api.add_user(f, "gone@offb.com")
    tok = api.login("offb", "gone@offb.com")
    assert api.get(tok, "/dashboard").status_code == 200
    assert api.post(f, f"/employees/{u['id']}/offboard").status_code == 200
    assert api.get(tok, "/dashboard").status_code == 401
    assert api.c.post("/api/v1/auth/login", json={"company_slug": "offb", "email": "gone@offb.com", "password": PW}).status_code == 401


def test_change_password(api):
    api.make_company("chpw")
    f = api.login("chpw", "founder@chpw.com")
    assert api.post(f, "/auth/change-password", {"current_password": "wrong", "new_password": "New-Passw0rd-1"}).status_code == 400
    assert api.post(f, "/auth/change-password", {"current_password": PW, "new_password": "short"}).status_code == 422
    assert api.post(f, "/auth/change-password", {"current_password": PW, "new_password": "New-Passw0rd-1"}).status_code == 204
    assert api.c.post("/api/v1/auth/login", json={"company_slug": "chpw", "email": "founder@chpw.com", "password": PW}).status_code == 401
    assert api.login("chpw", "founder@chpw.com", "New-Passw0rd-1")


def test_weak_password_rejected_on_company_creation(api):
    r = api.c.post("/api/v1/platform/companies", headers=api.h(api.admin_token()), json={
        "name": "Weak", "slug": "weakco", "founder_name": "W Founder", "founder_email": "w@weak.com", "founder_password": "password"})
    assert r.status_code == 422


def test_errors_use_uniform_envelope(api, org):
    r = api.get(org["emp"], "/employees")
    assert r.status_code == 403 and set(r.json()["error"]) == {"code", "message", "details"}
    r = api.post(org["founder"], "/employees", {"email": "not-an-email"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_login_without_company_finds_account_by_email(api, org):
    r = api.c.post("/api/v1/auth/login", json={"email": "emp@acme.com", "password": PW})
    assert r.status_code == 200
    me = api.get(r.json()["access_token"], "/auth/me").json()
    assert me["email"] == "emp@acme.com" and me["company"]["slug"] == "acme"
    # platform admin uses the same endpoint
    r = api.c.post("/api/v1/auth/login", json={"email": "admin@platform.com", "password": "Platform-Admin-1"})
    assert r.status_code == 200 and api.c.get("/api/v1/platform/stats", headers=api.h(r.json()["access_token"])).status_code == 200
    # wrong password / unknown email stay generic
    assert api.c.post("/api/v1/auth/login", json={"email": "emp@acme.com", "password": "nope"}).status_code == 401
    assert api.c.post("/api/v1/auth/login", json={"email": "ghost@nowhere.com", "password": PW}).status_code == 401


def test_login_without_company_ambiguous_email_needs_slug(api):
    for slug in ("dupa", "dupb"):
        api.make_company(slug, founder_email="same@dup.com")
    r = api.c.post("/api/v1/auth/login", json={"email": "same@dup.com", "password": PW})
    assert r.status_code == 409
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "dupb", "email": "same@dup.com", "password": PW})
    assert r.status_code == 200


_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_every_role_can_set_own_avatar_and_colleagues_can_view_it(api, org):
    h = api.h
    for role in ("founder", "hr", "mgr", "emp"):
        r = api.c.post("/api/v1/auth/me/avatar", headers=h(org[role]), files={"file": ("me.png", _PNG, "image/png")})
        assert r.status_code == 200, (role, r.text)
        v = r.json()["avatar_v"]
        assert api.get(org[role], "/auth/me").json()["avatar_v"] == v
    emp_id = org["ids"]["emp"]
    img = api.c.get(f"/api/v1/users/{emp_id}/avatar", headers=h(org["hr"]))
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == _PNG
    assert img.headers["x-content-type-options"] == "nosniff"
    assert api.c.get(f"/api/v1/users/{emp_id}/avatar").status_code == 401
    # replacing removes the old file; deleting clears it
    r2 = api.c.post("/api/v1/auth/me/avatar", headers=h(org["emp"]), files={"file": ("b.png", _PNG + b"1", "image/png")})
    assert r2.json()["avatar_v"] != v
    assert api.c.delete("/api/v1/auth/me/avatar", headers=h(org["emp"])).status_code == 204
    assert api.c.get(f"/api/v1/users/{emp_id}/avatar", headers=h(org["hr"])).status_code == 404
    assert api.get(org["emp"], "/auth/me").json()["avatar_v"] is None


def test_avatar_rejects_non_images_and_oversize(api, org):
    h = api.h(org["emp2"])
    for name, data in (("x.png", b"<script>alert(1)</script>"), ("x.png", b"GIF89a" + b"0" * 20), ("x.svg", b"<svg onload=alert(1)/>")):
        assert api.c.post("/api/v1/auth/me/avatar", headers=h, files={"file": (name, data, "image/png")}).status_code == 400
    big = _PNG + b"0" * (2 * 1024 * 1024)
    assert api.c.post("/api/v1/auth/me/avatar", headers=h, files={"file": ("big.png", big, "image/png")}).status_code == 413
    assert api.get(org["emp2"], "/auth/me").json()["avatar_v"] is None


def test_every_role_can_edit_own_profile_details_but_not_privileged_fields(api, org):
    for role in ("founder", "hr", "mgr", "emp"):
        r = api.c.patch("/api/v1/auth/me", headers=api.h(org[role]), json={"full_name": f"Renamed {role}", "designation": "Lead", "phone": " 555-0101 "})
        assert r.status_code == 200, (role, r.text)
        me = r.json()
        assert me["full_name"] == f"Renamed {role}" and me["designation"] == "Lead" and me["phone"] == "555-0101"
        assert api.get(org[role], "/auth/me").json()["phone"] == "555-0101"
    # role / email / manager are ignored (not in the schema), blank clears optional fields, bad names are rejected
    before = api.get(org["emp"], "/auth/me").json()
    r = api.c.patch("/api/v1/auth/me", headers=api.h(org["emp"]), json={"role": "founder", "email": "x@evil.com", "manager_id": 1, "phone": ""})
    assert r.status_code == 200 and r.json()["role"] == before["role"] == "employee" and r.json()["email"] == before["email"] and r.json()["phone"] is None
    assert api.c.patch("/api/v1/auth/me", headers=api.h(org["emp"]), json={"full_name": " a "}).status_code == 400
    assert api.c.patch("/api/v1/auth/me", headers=api.h(org["emp"]), json={"full_name": None}).status_code == 400
    assert api.c.patch("/api/v1/auth/me", json={"phone": "1"}).status_code == 401


def test_platform_login_checks_password_even_in_development(api, monkeypatch, tmp_path):
    """Regression B-002/B-005: development mode used to accept any 3+ char password for the platform admin
    (and the aliases admin/platform), and every attempt was appended to ./auth_activity.log."""
    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.chdir(tmp_path)
    for email, pw in [("admin@platform.com", "abc"), ("admin@platform.com", "Wrong-Pass-1"), ("admin", "xyz"),
                      ("platform", "xyz"), ("admin@worksphere.dev", "Admin@2205!"), ("admin@platform.com", "Demo-Passw0rd!")]:
        r = api.c.post("/api/v1/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401, (email, pw, r.status_code)
    ok = api.c.post("/api/v1/auth/login", json={"email": "admin@platform.com", "password": "Platform-Admin-1"})
    assert ok.status_code == 200
    assert not (tmp_path / "auth_activity.log").exists()


def test_company_and_platform_login_check_password_in_development(api, org, monkeypatch):
    """Regression B-002: the same dev bypass existed for company users (any 3+ char password, role aliases like
    'manager'/'hr', silent password rewrite, auto-activation) and in /auth/platform/login."""
    monkeypatch.setattr(get_settings(), "environment", "development")
    for email, pw in [("founder@acme.com", "abc"), ("hr@acme.com", "Wrong-Pass-1"), ("manager", "abcdef"),
                      ("hr", "abcdef"), ("employee", "abcdef"), ("founder", "abcdef"), ("emp@acme.com", "Admin@2205!")]:
        login_limiter.clear()
        r = api.c.post("/api/v1/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401, (email, pw, r.status_code)
    login_limiter.clear()
    for pw in ("Admin@2205!", "Demo-Passw0rd!", "abc"):
        r = api.c.post("/api/v1/auth/platform/login", json={"email": "admin@platform.com", "password": pw})
        assert r.status_code == 401, pw
    # the real password still works, and a wrong guess did not overwrite it
    assert api.c.post("/api/v1/auth/login", json={"email": "emp@acme.com", "password": PW}).status_code == 200
