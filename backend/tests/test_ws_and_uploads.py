"""Open sockets re-prove their session; uploads are allow-listed and content-checked; tenants stay apart."""
import io
from datetime import date, timedelta
import zipfile

import pytest
from starlette.websockets import WebSocketDisconnect

from app.modules.notifications import router as ws_router
from tests.conftest import PW
from app.db.base import utcnow


@pytest.fixture
def fast_recheck(monkeypatch):
    monkeypatch.setattr(ws_router, "WS_RECHECK_SECONDS", 0.2)


def _fresh_login(api, email):
    api.add_user(_founder(api), email, "employee")
    r = api.c.post("/api/v1/auth/login", json={"company_slug": "acme", "email": email, "password": PW})
    return r.json()


def _founder(api):
    return api.login("acme", "founder@acme.com")


def _expect_closed(ws, code=4401):
    with pytest.raises(WebSocketDisconnect) as e:
        for _ in range(20):  # skip any pong frames that were already queued
            ws.receive_json()
    assert e.value.code == code


# ---------------------------------------------------------------- websockets

def test_socket_closes_after_logout(api, org, fast_recheck):
    t = _fresh_login(api, "ws-logout@acme.com")
    with api.c.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": t["access_token"]})
        assert ws.receive_json()["type"] == "ready"
        api.c.post("/api/v1/auth/logout", headers=api.h(t["access_token"]))
        _expect_closed(ws)


def test_socket_closes_after_password_reset(api, org, fast_recheck):
    t = _fresh_login(api, "ws-reset@acme.com")
    uid = api.get(t["access_token"], "/auth/me").json()["id"]
    with api.c.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": t["access_token"]})
        assert ws.receive_json()["type"] == "ready"
        assert api.post(org["hr"], f"/employees/{uid}/reset-password", {"new_password": "Temp1234"}).status_code == 204
        _expect_closed(ws)


def test_socket_closes_when_the_account_is_offboarded(api, org, fast_recheck):
    t = _fresh_login(api, "ws-off@acme.com")
    uid = api.get(t["access_token"], "/auth/me").json()["id"]
    with api.c.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": t["access_token"]})
        assert ws.receive_json()["type"] == "ready"
        assert api.post(org["hr"], f"/employees/{uid}/offboard").status_code == 200
        _expect_closed(ws)


def test_healthy_socket_stays_open_across_rechecks(api, org, fast_recheck):
    import time

    t = _fresh_login(api, "ws-ok@acme.com")
    with api.c.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": t["access_token"]})
        assert ws.receive_json()["type"] == "ready"
        time.sleep(0.8)  # several recheck rounds
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_meeting_socket_closes_after_logout(api, org, fast_recheck):
    t = _fresh_login(api, "ws-meet@acme.com")
    m = api.post(t["access_token"], "/meetings", {"title": "Stand-up"}).json()
    with api.c.websocket_connect(f"/api/v1/meetings/ws/{m['room_id']}") as ws:
        ws.send_json({"type": "auth", "token": t["access_token"]})
        assert ws.receive_json()["type"] == "joined"
        api.c.post("/api/v1/auth/logout", headers=api.h(t["access_token"]))
        _expect_closed(ws)


def test_meeting_room_ids_do_not_cross_tenants(api, org):
    api.ensure_company("globex")
    other = api.login("globex", "founder@globex.com")
    m = api.post(org["founder"], "/meetings", {"title": "Board"}).json()
    with api.c.websocket_connect(f"/api/v1/meetings/ws/{m['room_id']}") as ws:
        ws.send_json({"type": "auth", "token": other})
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["reason"] == "not_found"


# ------------------------------------------------------------------- uploads

def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
    return buf.getvalue()


@pytest.fixture
def doc_url(api, org):
    return f"/api/v1/employees/{org['ids']['emp']}/documents"


def _upload(api, org, url, name, data):
    return api.c.post(url, headers=api.h(org["emp"]), files={"file": (name, data, "application/octet-stream")}, data={"doc_type": "other"})


@pytest.mark.parametrize("name,data", [
    ("a.pdf", b"%PDF-1.7 body"), ("a.png", b"\x89PNG\r\n\x1a\n...."), ("a.jpg", b"\xff\xd8\xff\xe0 jfif"), ("a.docx", _zip()),
    ("a.xlsx", _zip()), ("a.txt", "héllo".encode()), ("a.csv", b"a,b\n1,2\n"), ("a.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "),
])
def test_allowed_types_with_matching_content_are_accepted(api, org, doc_url, name, data):
    r = _upload(api, org, doc_url, name, data)
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("name,data", [
    ("evil.html", b"<script>alert(1)</script>"), ("evil.svg", b"<svg onload=alert(1)/>"), ("run.exe", b"MZ\x90\x00"),
    ("run.js", b"alert(1)"), ("noext", b"%PDF-1.4"), ("a.php", b"<?php ?>"), ("a.pdf.html", b"%PDF"),
    ("a.jar", _zip()), ("a.svgz", b"\x1f\x8b"), ("a.HTM", b"<html>"),
])
def test_other_types_are_refused(api, org, doc_url, name, data):
    assert _upload(api, org, doc_url, name, data).status_code == 400


@pytest.mark.parametrize("name,data", [
    ("fake.pdf", b"<html><script>1</script></html>"), ("fake.png", b"%PDF-1.4"), ("fake.docx", b"just text"),
    ("fake.txt", b"bin\x00ary"), ("fake.csv", b"\xff\xfe\x00bad"), ("fake.jpg", b""),
])
def test_content_must_match_the_extension(api, org, doc_url, name, data):
    r = _upload(api, org, doc_url, name, data)
    assert r.status_code == 400 and "match" in r.text


def test_task_attachments_use_the_same_rules(api, org):
    p = api.post(org["mgr"], "/projects", {"name": "Upload rules", "due_date": (utcnow().date() + timedelta(days=30)).isoformat(), "member_ids": [org["ids"]["emp"]]}).json()
    tr = api.post(org["mgr"], f"/projects/{p['id']}/tasks", {"title": "Upload task", "assignee_id": org["ids"]["emp"]})
    assert tr.status_code == 201, tr.text
    t = tr.json()
    url = f"/api/v1/tasks/{t['id']}/attachments"
    bad = api.c.post(url, headers=api.h(org["emp"]), files={"file": ("x.html", b"<b>", "text/html")})
    assert bad.status_code == 400
    ok = api.c.post(url, headers=api.h(org["emp"]), files={"file": ("x.txt", b"hello", "text/plain")})
    assert ok.status_code == 201
    dl = api.c.get(f"/api/v1/attachments/{ok.json()['id']}/download", headers=api.h(org["emp"]))
    assert dl.headers["content-disposition"].startswith("attachment") and dl.headers["x-content-type-options"] == "nosniff"


def test_documents_are_not_downloadable_across_tenants(api, org, doc_url):
    api.ensure_company("globex")
    other = api.login("globex", "founder@globex.com")
    doc = _upload(api, org, doc_url, "a.pdf", b"%PDF-1.4 secret").json()
    assert api.get(other, f"/employees/{org['ids']['emp']}/documents/{doc['id']}/download").status_code in (403, 404)
    assert api.get(other, f"/documents/{doc['id']}/download").status_code in (403, 404)
