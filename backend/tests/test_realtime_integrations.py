"""Webhooks, WebSockets, WebRTC signaling, platform ops, migrations."""
import json
from datetime import timedelta

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.security import decrypt, sign_payload
from app.db.base import TenantBase, utcnow
from app.db.platform_models import Company
from app.db.session import platform_session
from app.db.tenant_models import WebhookDelivery
from app.modules.webhooks.service import process_due
from app.tenancy.manager import migrate_tenant, tenants
from tests.conftest import PW


def _company(slug):
    with platform_session() as db:
        c = db.scalar(select(Company).where(Company.slug == slug))
        db.expunge(c)
        return c


@pytest.fixture
def allow_private_webhooks():
    s = get_settings()
    old = s.webhook_allow_private_urls
    s.webhook_allow_private_urls = True
    yield
    s.webhook_allow_private_urls = old


# ---- webhooks ---------------------------------------------------------------------------------

def test_webhook_url_ssrf_protection(api, org):
    f = org["founder"]
    for url in ("http://example.com/hook", "https://127.0.0.1/x", "https://localhost/x", "https://169.254.169.254/latest", "ftp://x.com/a", "not a url"):
        r = api.post(f, "/webhooks", {"url": url, "events": ["task.created"]})
        assert r.status_code == 400, url
    assert api.post(f, "/webhooks", {"url": "https://8.8.8.8/hook", "events": ["bogus.event"]}).status_code == 422


def test_webhook_signed_delivery_retry_and_log(api, allow_private_webhooks):
    api.make_company("hooks")
    f = api.login("hooks", "founder@hooks.com")
    created = api.post(f, "/webhooks", {"url": "http://receiver.example.com/hook", "events": ["employee.created"]}).json()
    secret = created["secret"]
    assert secret.startswith("whsec_")
    assert "secret" not in api.get(f, "/webhooks").json()["items"][0]  # shown only once
    api.add_user(f, "newbie@hooks.com")

    company = _company("hooks")
    received: list[httpx.Request] = []
    behaviour = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(behaviour["status"])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with tenants.session_for(company) as db:
        assert db.scalar(select(WebhookDelivery.id)) is not None
        behaviour["status"] = 500
        assert process_due(db, client) == 1
        d = db.scalar(select(WebhookDelivery))
        assert d.status == "pending" and d.attempts == 1 and d.last_status_code == 500
        assert d.next_attempt_at > utcnow().replace(tzinfo=None) if d.next_attempt_at.tzinfo is None else d.next_attempt_at > utcnow()
        assert process_due(db, client) == 0  # backoff: not due yet
        d.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
        behaviour["status"] = 200
        assert process_due(db, client) == 1
        d = db.scalar(select(WebhookDelivery))
        assert d.status == "success" and d.attempts == 2 and d.delivered_at

    req = received[-1]
    body = req.content
    ts = req.headers["x-worksphere-timestamp"]
    assert req.headers["x-worksphere-signature"] == sign_payload(secret, ts, body)
    assert req.headers["x-worksphere-event"] == "employee.created"
    payload = json.loads(body)
    assert payload["event"] == "employee.created" and payload["data"]["email"] == "newbie@hooks.com"

    log = api.get(f, "/webhooks/deliveries/log?status=success").json()
    assert log["total"] == 1 and log["items"][0]["attempts"] == 2


def test_webhook_gives_up_after_max_attempts_and_can_be_retried(api, allow_private_webhooks):
    api.make_company("hooks2")
    f = api.login("hooks2", "founder@hooks2.com")
    api.post(f, "/webhooks", {"url": "http://down.example.com/hook", "events": ["employee.created"]})
    api.add_user(f, "u@hooks2.com")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    company = _company("hooks2")
    with tenants.session_for(company) as db:
        for _ in range(get_settings().webhook_max_attempts):
            db.query(WebhookDelivery).update({"next_attempt_at": utcnow() - timedelta(seconds=1)})
            db.commit()
            process_due(db, client)
        d = db.scalar(select(WebhookDelivery))
        assert d.status == "failed" and d.attempts == get_settings().webhook_max_attempts
        did = d.id
    assert api.post(f, f"/webhooks/deliveries/{did}/retry").json()["status"] == "pending"


def test_webhook_test_endpoint_and_secret_rotation(api, allow_private_webhooks, monkeypatch):
    api.make_company("hooks3")
    f = api.login("hooks3", "founder@hooks3.com")
    h = api.post(f, "/webhooks", {"url": "http://ok.example.com/h", "events": ["task.created"]}).json()
    real = httpx.Client
    monkeypatch.setattr("app.modules.webhooks.router.httpx.Client", lambda: real(transport=httpx.MockTransport(lambda r: httpx.Response(204))))
    assert api.post(f, f"/webhooks/{h['id']}/test").json()["status"] == "success"
    assert api.post(f, f"/webhooks/{h['id']}/rotate-secret").json()["secret"] != h["secret"]


def test_webhooks_are_tenant_scoped(api, org, allow_private_webhooks):
    api.make_company("hooks4")
    fa = api.login("hooks4", "founder@hooks4.com")
    fb = api.login("acme", "founder@acme.com")
    api.post(fa, "/webhooks", {"url": "http://x.example.com/h", "events": ["employee.created"]})
    assert api.get(fb, "/webhooks").json()["items"] == [] or all("hooks4" not in w["url"] for w in api.get(fb, "/webhooks").json()["items"])
    api.add_user(fb, "tenantb-user@acme.com")
    with tenants.session_for(_company("hooks4")) as db:
        assert db.query(WebhookDelivery).count() == 0  # acme's event never reaches hooks4's outbox


# ---- websockets -------------------------------------------------------------------------------

def test_notification_websocket_push_and_auth(client, api, org):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "auth", "token": "bad"})
            ws.receive_json()
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": org["emp2"]})
        assert ws.receive_json() == {"type": "ready"}
        # a manager assigns a task -> the employee receives a live notification
        p = api.post(org["mgr"], "/projects", {"name": "Realtime Project"}).json()
        api.post(org["mgr"], f"/projects/{p['id']}/tasks", {"title": "Live task", "assignee_id": org["ids"]["emp2"]})
        seen = []
        for _ in range(4):
            m = ws.receive_json()
            seen.append(m)
            if m.get("type") == "notification":
                break
        notif = [m for m in seen if m["type"] == "notification"][0]
        assert notif["data"]["title"] == "New task assigned" and notif["data"]["body"] == "Live task"
        ws.send_json({"type": "ping"})
        for _ in range(5):  # live-update events may arrive before the pong
            if ws.receive_json() == {"type": "pong"}:
                break
        else:
            raise AssertionError("no pong")


def test_websocket_does_not_leak_across_tenants(client, api, org):
    api.ensure_company("wsiso")
    fb = api.login("wsiso", "founder@wsiso.com")
    # Both founders are user id 1 in their own database: only the tenant key separates their sockets.
    acme_founder_id = api.get(org["founder"], "/auth/me").json()["id"]
    wsiso_founder_id = api.get(fb, "/auth/me").json()["id"]
    assert acme_founder_id == wsiso_founder_id
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": fb})
        assert ws.receive_json()["type"] == "ready"
        api.add_user(org["founder"], "ws-leak@acme.com", manager_id=acme_founder_id)  # notifies acme's user 1
        api.add_user(fb, "ws-own@wsiso.com", manager_id=wsiso_founder_id)  # notifies wsiso's user 1
        msg = ws.receive_json()
        assert msg["type"] == "notification" and "ws-own" in msg["data"]["body"].lower() + "ws-own"
        assert "acme" not in json.dumps(msg).lower()
        assert msg["data"]["body"] == "Ws-Own Test now reports to you."


def test_webrtc_signaling_between_two_peers(client, api, org):
    room = api.post(org["mgr"], "/meetings", {"title": "Standup", "invitee_ids": [org["ids"]["emp"]]}).json()["room_id"]
    with client.websocket_connect(f"/api/v1/meetings/ws/{room}") as a:
        a.send_json({"type": "auth", "token": org["mgr"]})
        ja = a.receive_json()
        assert ja["type"] == "joined" and ja["peers"] == []
        with client.websocket_connect(f"/api/v1/meetings/ws/{room}") as b:
            b.send_json({"type": "auth", "token": org["emp"]})
            jb = b.receive_json()
            assert jb["type"] == "joined" and [p["peer_id"] for p in jb["peers"]] == [ja["peer_id"]]
            assert a.receive_json()["type"] == "peer-joined"
            b.send_text(json.dumps({"type": "offer", "to": ja["peer_id"], "data": {"sdp": "v=0..."}}))
            got = a.receive_json()
            assert got == {"type": "offer", "from": jb["peer_id"], "data": {"sdp": "v=0..."}}
            a.send_text(json.dumps({"type": "answer", "to": jb["peer_id"], "data": {"sdp": "ans"}}))
            assert b.receive_json()["type"] == "answer"
            b.send_text(json.dumps({"type": "screen-share", "active": True}))
            assert a.receive_json() == {"type": "screen-share", "from": jb["peer_id"], "active": True}
            # relay to a non-existent / foreign peer is silently dropped; sender can't spoof `from`
            b.send_text(json.dumps({"type": "ice", "to": "nobody", "from": "spoof", "data": {}}))
        assert a.receive_json()["type"] == "peer-left"


def test_signaling_rooms_are_tenant_scoped_and_ended_rooms_closed(client, api, org):
    room = api.post(org["mgr"], "/meetings", {"title": "Private"}).json()["room_id"]
    api.ensure_company("wsiso")
    outsider = api.login("wsiso", "founder@wsiso.com")
    with client.websocket_connect(f"/api/v1/meetings/ws/{room}") as ws:
        ws.send_json({"type": "auth", "token": outsider})
        assert ws.receive_json() == {"type": "error", "reason": "not_found"}
    assert api.post(org["emp"], f"/meetings/{room}/end").status_code == 404  # not invited: the meeting does not exist for them (it used to be 403)
    assert api.post(org["mgr"], f"/meetings/{room}/end").json()["status"] == "ended"
    with client.websocket_connect(f"/api/v1/meetings/ws/{room}") as ws:
        ws.send_json({"type": "auth", "token": org["mgr"]})
        assert ws.receive_json() == {"type": "error", "reason": "ended"}
    with pytest.raises(Exception):
        with client.websocket_connect(f"/api/v1/meetings/ws/{room}") as ws:  # no auth message
            ws.receive_json()


def test_ice_config_uses_short_lived_turn_credentials(api, org):
    s = get_settings()
    old = (s.turn_url, s.turn_secret)
    s.turn_url, s.turn_secret = "turn:turn.example.com:3478", "shared-secret"
    try:
        servers = api.get(org["emp"], "/meetings/ice-config").json()["iceServers"]
    finally:
        s.turn_url, s.turn_secret = old
    turn = [x for x in servers if "username" in x][0]
    assert turn["urls"] == ["turn:turn.example.com:3478"] and ":" in turn["username"] and turn["credential"]
    assert "shared-secret" not in json.dumps(servers)
    assert any("stun:" in u for x in servers for u in x["urls"])


# ---- notifications REST -----------------------------------------------------------------------

def test_notifications_read_state_is_per_user(api, org):
    items = api.get(org["emp"], "/notifications").json()["items"]
    assert items
    nid = items[0]["id"]
    assert api.post(org["emp2"], f"/notifications/{nid}/read").status_code == 404  # someone else's
    assert api.post(org["emp"], f"/notifications/{nid}/read").status_code == 204
    assert api.post(org["emp"], "/notifications/read-all").status_code == 204
    assert api.get(org["emp"], "/notifications/unread-count").json()["count"] == 0


# ---- platform ops & migrations ------------------------------------------------------------------

def test_platform_company_management(api):
    adm = api.admin_token()
    api.make_company("ops1")
    assert api.c.post("/api/v1/platform/companies", headers=api.h(adm), json={
        "name": "Dup", "slug": "ops1", "founder_name": "D F", "founder_email": "d@ops1.com", "founder_password": PW}).status_code == 409
    for bad in ("Bad Slug", "admin", "-x", "a"):
        r = api.c.post("/api/v1/platform/companies", headers=api.h(adm), json={
            "name": "Bad", "slug": bad, "founder_name": "D F", "founder_email": "d@bad.com", "founder_password": PW})
        assert r.status_code == 422, bad
    cid = [c for c in api.get(adm, "/platform/companies").json()["items"] if c["slug"] == "ops1"][0]["id"]
    usage = api.get(adm, f"/platform/companies/{cid}/usage").json()
    assert usage["users"] == 1 and usage["db_size_bytes"] > 0
    bk = api.post(adm, f"/platform/companies/{cid}/backup").json()
    assert bk["size_bytes"] > 0 and bk["file"].startswith("ops1-")
    assert api.post(adm, "/platform/migrate").json()["failed"] == []
    assert api.get(adm, "/platform/stats").json()["companies"] >= 1
    assert api.get(adm, "/platform/companies/99999").status_code == 404


def test_failed_provisioning_leaves_no_company(api, monkeypatch):
    adm = api.admin_token()
    import app.modules.platform.router as pr
    monkeypatch.setattr(pr, "seed_tenant", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/v1/platform/companies", headers=api.h(adm), json={
            "name": "Broken", "slug": "broken", "founder_name": "B F", "founder_email": "b@broken.com", "founder_password": PW})
    assert r.status_code == 500
    slugs = [c["slug"] for c in api.get(adm, "/platform/companies").json()["items"]]
    assert "broken" not in slugs


def test_tenant_schema_matches_models_and_is_at_head(api, org):
    eng = tenants.engine_for(_company("acme"))
    with eng.connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar() == "0020"
        diff = compare_metadata(MigrationContext.configure(conn), TenantBase.metadata)
    assert diff == [], f"migrations are out of sync with models: {diff}"
    migrate_tenant(eng)  # idempotent


def test_platform_schema_matches_models(client):
    from app.db.base import PlatformBase
    from app.db.session import get_platform_engine
    with get_platform_engine().connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), PlatformBase.metadata) == []


def test_health_and_docs(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/openapi.json").status_code == 200
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]
