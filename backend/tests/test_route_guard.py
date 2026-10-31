"""Structural guards: no route can be added without authentication, and no route lets the client choose the tenant.

If you add a deliberately public endpoint, add it to PUBLIC with a reason; the test then documents the decision.
"""
import re

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from app.deps import get_ctx, get_platform_admin
from app.main import app

# (METHOD, path) -> why it is reachable without a session. Every one of these is rate limited or reveals nothing.
PUBLIC = {
    ("POST", "/api/v1/auth/login"): "sign-in (rate limited, generic failure)",
    ("POST", "/api/v1/auth/platform/login"): "platform sign-in",
    ("POST", "/api/v1/auth/refresh"): "uses the refresh token itself",
    ("POST", "/api/v1/auth/mfa/verify"): "second step, needs the short-lived mfa token",
    ("POST", "/api/v1/auth/password-reset/request"): "always answers 202, rate limited",
    ("POST", "/api/v1/auth/password-reset/confirm"): "needs the e-mailed one-time token",
    ("POST", "/api/v1/auth/verify-email/confirm"): "needs the e-mailed one-time token",
    ("POST", "/api/v1/auth/logout"): "tokenless by design: presenting a token can only ever revoke that token",
    ("GET", "/api/v1/auth/session"): "validates the presented token itself and answers 401 without one",
    ("GET", "/api/health"): "liveness probe",
}
# WebSockets authenticate with a first message (so the token never sits in a URL) and re-check the session every WS_RECHECK_SECONDS.
WEBSOCKETS = {"/ws", "/meetings/ws/{room_id}"}  # paths relative to the /api/v1 prefix
NEVER_FROM_CLIENT = {"company_id", "tenant_id", "company_slug", "tenant", "tenant_slug", "db_url", "database_url"}


def _calls(dependant):
    yield dependant.call
    for d in dependant.dependencies:
        yield from _calls(d)


def _flat():
    """Every route, including those behind include_router (newer FastAPI keeps them in lazy `_IncludedRouter` objects)."""
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            yield from r.effective_route_contexts()
        else:
            yield r


def _api_routes():
    return [r for r in _flat() if isinstance(getattr(r, "original_route", r), APIRoute) and r.path.startswith("/api")]


def test_the_route_walk_sees_the_whole_application():
    assert len(_api_routes()) > 250  # a structural change in FastAPI that hides routes would make every guard below pass vacuously


def _auth_dependency(route) -> bool:
    return any(c in (get_ctx, get_platform_admin) for c in _calls(route.dependant))


def test_every_route_requires_a_session_unless_explicitly_public():
    unguarded = []
    for r in _api_routes():
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            if (m, r.path) in PUBLIC or _auth_dependency(r):
                continue
            unguarded.append(f"{m} {r.path}")
    assert unguarded == [], "routes reachable without authentication (add Depends(get_ctx) or list them in PUBLIC with a reason)"


def test_public_allow_list_has_no_stale_entries():
    existing = {(m, r.path) for r in _api_routes() for m in r.methods}
    assert [k for k in PUBLIC if k not in existing] == []


def test_websocket_routes_are_the_known_ones():
    assert {getattr(r, "original_route", r).path for r in _flat() if isinstance(getattr(r, "original_route", r), APIWebSocketRoute)} == WEBSOCKETS


def test_no_route_lets_the_client_choose_the_tenant():
    offenders = []
    for r in _api_routes():
        # platform admins manage companies; the public pre-sign-in endpoints must name the company because there is no session yet
        if r.path.startswith("/api/v1/platform") or any((m, r.path) in PUBLIC for m in r.methods):
            continue
        names = {p.name for p in r.dependant.path_params + r.dependant.query_params + r.dependant.header_params + r.dependant.cookie_params}
        body_fields = set()
        for b in r.dependant.body_params:
            model = getattr(b.field_info.annotation, "model_fields", None)
            body_fields |= set(model) if model else {b.name}
        bad = (names | body_fields) & NEVER_FROM_CLIENT
        if bad:
            offenders.append(f"{sorted(r.methods)} {r.path}: {sorted(bad)}")
    assert offenders == []


def _fill(route, value_for) -> str:
    path = route.path
    for p in route.dependant.path_params:
        path = path.replace("{" + p.name + "}", str(value_for(p)))
    return re.sub(r"\{[^}]+\}", "x", path)


def _is_int(p) -> bool:
    return p.field_info.annotation is int


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_without_a_token_every_protected_route_answers_401(client, method):
    wrong = []
    for r in _api_routes():
        if method not in r.methods or (method, r.path) in PUBLIC:
            continue
        resp = client.request(method, _fill(r, lambda p: 1 if _is_int(p) else "x"), json={})
        if resp.status_code != 401:
            wrong.append(f"{method} {r.path} -> {resp.status_code}")
    assert wrong == []


# Reads and writes aimed at ids that exist nowhere must never succeed or crash, whoever asks. An id that belongs to another company
# looks exactly like this to the caller, because each company has its own database.
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_unknown_ids_are_refused_for_a_signed_in_founder(api, client, method):
    api.ensure_company("guardco")
    tok = api.login("guardco", "founder@guardco.com")
    bad = []
    for r in _api_routes():
        if method not in r.methods or (method, r.path) in PUBLIC or not r.dependant.path_params:
            continue
        if r.path.startswith("/api/v1/platform") or "/ws" in r.path or r.path.endswith("/ice-config"):
            continue
        url = _fill(r, lambda p: 987654 if _is_int(p) else "no-such-thing")
        resp = client.request(method, url, headers=api.h(tok), json={})
        if resp.status_code < 400 or resp.status_code >= 500:
            bad.append(f"{method} {r.path} -> {resp.status_code}")
    assert bad == []
