"""Browser sessions: httpOnly cookies bound to the browser that signed in (token copied elsewhere is useless)."""
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PW

WEB = {"X-WS-Client": "web"}


def _web_login(client, email="founder@acme.com", password=PW):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=WEB)


def test_web_login_sets_httponly_cookies_and_returns_no_tokens(api, org):
    with TestClient(app) as browser:
        r = _web_login(browser)
        assert r.status_code == 200
        body = r.json()
        assert not body.get("access_token") and not body.get("refresh_token")
        assert body["role"] == "founder"
        set_cookie = " ".join(r.headers.get_list("set-cookie")).lower()
        for name in ("ws_access", "ws_refresh", "ws_device"):
            assert name in set_cookie
        for name in ("ws_access=", "ws_refresh=", "ws_device="):
            part = next(c for c in r.headers.get_list("set-cookie") if c.startswith(name))
            assert "httponly" in part.lower() and "samesite=strict" in part.lower()
        assert browser.get("/api/v1/auth/me").status_code == 200


def test_session_cookie_copied_to_another_browser_is_rejected(api, org):
    with TestClient(app) as browser:
        _web_login(browser)
        stolen = browser.cookies.get("ws_access")
        assert stolen
        with TestClient(app) as other:  # a different browser: has the token but not this browser's device cookie
            other.cookies.set("ws_access", stolen)
            assert other.get("/api/v1/auth/me").status_code == 401
            other.cookies.set("ws_device", "some-other-browsers-device-id")
            assert other.get("/api/v1/auth/me").status_code == 401
            r = other.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {stolen}"})
            assert r.status_code == 401  # nor as a bearer token
        # the real browser is unaffected
        assert browser.get("/api/v1/auth/me").status_code == 200


def test_two_browsers_have_independent_sessions(api, org):
    with TestClient(app) as a, TestClient(app) as b:
        _web_login(a, "founder@acme.com")
        _web_login(b, "hr@acme.com")
        assert a.get("/api/v1/auth/me").json()["email"] == "founder@acme.com"
        assert b.get("/api/v1/auth/me").json()["email"] == "hr@acme.com"


def test_cookie_requests_that_change_data_need_the_csrf_header(api, org):
    with TestClient(app) as browser:
        _web_login(browser)
        r = browser.patch("/api/v1/auth/me", json={"designation": "CEO"})
        assert r.status_code == 403
        r = browser.patch("/api/v1/auth/me", json={"designation": "CEO"}, headers=WEB)
        assert r.status_code == 200


def test_refresh_and_logout_with_cookies(api, org):
    with TestClient(app) as browser:
        _web_login(browser)
        old = browser.cookies.get("ws_access")
        r = browser.post("/api/v1/auth/refresh", headers=WEB)
        assert r.status_code == 200 and browser.get("/api/v1/auth/me").status_code == 200
        assert browser.cookies.get("ws_access") != old
        assert browser.post("/api/v1/auth/refresh").status_code == 403  # no CSRF header
        r = browser.post("/api/v1/auth/logout", headers=WEB)
        assert r.status_code == 204
        assert browser.get("/api/v1/auth/me").status_code == 401
        assert browser.post("/api/v1/auth/refresh", headers=WEB).status_code == 401


def test_platform_admin_web_session_is_bound_too(api):
    with TestClient(app) as browser:
        r = browser.post("/api/v1/auth/login", json={"email": "admin@platform.com", "password": "Platform-Admin-1"}, headers=WEB)
        assert r.status_code == 200 and r.json()["role"] == "platform_admin"
        assert browser.get("/api/v1/platform/companies").status_code == 200
        stolen = browser.cookies.get("ws_access")
        with TestClient(app) as other:
            other.cookies.set("ws_access", stolen)
            assert other.get("/api/v1/platform/companies").status_code == 401


def test_api_clients_without_the_web_header_still_get_bearer_tokens(api, org):
    r = api.c.post("/api/v1/auth/login", json={"email": "founder@acme.com", "password": PW})
    assert r.json()["access_token"] and r.json()["refresh_token"]
    assert api.get(r.json()["access_token"], "/auth/me").status_code == 200


def test_websocket_authenticates_with_the_session_cookie(api, org):
    with TestClient(app) as browser:
        _web_login(browser)
        with browser.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "auth"})
            assert ws.receive_json()["type"] == "ready"
        with TestClient(app) as other:
            other.cookies.set("ws_access", browser.cookies.get("ws_access"))
            with other.websocket_connect("/api/v1/ws") as ws:
                ws.send_json({"type": "auth"})
                try:
                    msg = ws.receive_json()
                except Exception:
                    msg = None
                assert not msg or msg.get("type") != "ready"
