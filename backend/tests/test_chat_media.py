"""Chat extras: photos, documents, music, voice messages, stickers and reactions; every file goes through the same safety rules as other uploads."""
import pytest

from app import storage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"x" * 64


@pytest.fixture(scope="module")
def dm(api, org):
    c = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["mgr"]}).json()
    return c["id"]


def up(api, tok, cid, name, data, ctype="application/octet-stream", **form):
    return api.c.post(f"/api/v1/chat/conversations/{cid}/attachments", headers=api.h(tok), files={"file": (name, data, ctype)}, data=form)


def test_a_photo_is_stored_shown_inline_and_visible_only_to_the_conversation(api, org, dm):
    r = up(api, org["emp"], dm, "holiday.png", PNG, "image/png", caption=" Look at this ")
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["kind"] == "image" and m["body"] == "Look at this" and m["preview"] == "📷 Photo"
    assert m["file"]["name"] == "holiday.png" and m["file"]["size"] == len(PNG) and m["file"]["url"] == f"/chat/messages/{m['id']}/file"
    got = api.c.get("/api/v1" + m["file"]["url"], headers=api.h(org["mgr"]))
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png" and got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-disposition"].startswith("inline")
    assert "sandbox" in got.headers["content-security-policy"]
    assert api.c.get("/api/v1" + m["file"]["url"], headers=api.h(org["emp2"])).status_code == 404      # not in the conversation
    assert api.c.get("/api/v1" + m["file"]["url"]).status_code == 401
    seen = [x for x in api.get(org["mgr"], f"/chat/conversations/{dm}/messages").json()["items"] if x["id"] == m["id"]][0]
    assert seen["kind"] == "image" and seen["file"]["name"] == "holiday.png"
    last = [c for c in api.get(org["mgr"], "/chat/conversations").json()["items"] if c["id"] == dm][0]["last_message"]
    assert last["preview"] == "📷 Photo"


def test_documents_are_always_downloaded_never_rendered(api, org, dm):
    m = up(api, org["mgr"], dm, "plan.pdf", PDF, "application/pdf").json()
    assert m["kind"] == "file" and m["preview"] == "📎 plan.pdf"
    got = api.c.get("/api/v1" + m["file"]["url"], headers=api.h(org["emp"]))
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/octet-stream" and got.headers["content-disposition"].startswith("attachment")


def test_music_and_voice_messages(api, org, dm):
    song = up(api, org["emp"], dm, "track.mp3", MP3, "audio/mpeg", duration="185").json()
    assert song["kind"] == "audio" and song["file"]["mime"] == "audio/mpeg" and song["file"]["duration_s"] == 185 and song["preview"] == "🎵 track.mp3"
    assert up(api, org["emp"], dm, "clip.wav", WAV).json()["kind"] == "audio"
    assert up(api, org["emp"], dm, "clip.ogg", OGG).json()["kind"] == "audio"
    voice = up(api, org["emp"], dm, "recording.webm", WEBM, "audio/webm", voice="true", duration="12").json()
    assert voice["kind"] == "audio" and voice["file"]["name"].startswith("voice-") and voice["file"]["name"].endswith(".webm") and voice["preview"] == "🎤 Voice message"
    played = api.c.get("/api/v1" + voice["file"]["url"], headers=api.h(org["mgr"]))
    assert played.status_code == 200 and played.headers["content-type"] == "audio/webm"
    assert up(api, org["emp"], dm, "x.mp3", MP3, duration="99999").status_code == 422                 # absurd duration


@pytest.mark.parametrize("name,data", [
    ("page.html", b"<script>alert(1)</script>"), ("logo.svg", b"<svg onload=alert(1)/>"), ("run.exe", b"MZ\x90\x00"), ("noext", PNG),
    ("fake.png", b"this is not a png"), ("fake.mp3", b"not audio at all"), ("video.webm", WEBM), ("archive.zip", b"PK\x03\x04"),
])
def test_unsafe_or_mismatched_files_are_refused(api, org, dm, name, data):
    r = up(api, org["emp"], dm, name, data)
    assert r.status_code == 400, (name, r.text)


def test_size_limit(api, org, dm, monkeypatch):
    monkeypatch.setattr(storage, "CHAT_MAX_BYTES", 100)
    assert up(api, org["emp"], dm, "big.png", PNG + b"\x00" * 200).status_code == 413


def test_the_communication_rules_apply_to_files_too(api, org):
    f_id = api.get(org["founder"], "/auth/me").json()["id"]
    assert api.post(org["emp"], "/chat/conversations", {"user_id": f_id}).status_code == 403          # employee cannot reach the founder
    dm_ep = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["emp2"]}).json()["id"]
    assert up(api, org["emp2"], dm_ep, "ok.png", PNG).status_code == 201                              # peers can
    assert up(api, org["mgr2"], dm_ep, "no.png", PNG).status_code == 404                              # a stranger cannot
    assert api.post(org["mgr2"], f"/chat/conversations/{dm_ep}/stickers", {"sticker": "heart"}).status_code == 404


def test_stickers(api, org, dm):
    cat = api.get(org["emp"], "/chat/stickers").json()
    assert len(cat["items"]) >= 20 and {"id", "emoji", "label", "category"} <= set(cat["items"][0]) and "👍" in cat["reactions"]
    assert {i["category"] for i in cat["items"]} == {"Reactions", "Celebrate", "Work", "Fun"}
    r = api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {"sticker": "party"})
    assert r.status_code == 201 and r.json()["kind"] == "sticker" and r.json()["sticker"] == {"id": "party", "emoji": "🎉", "label": "Celebrate"}
    assert r.json()["preview"] == "🎉 Sticker"
    assert api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {"sticker": "<script>"}).status_code == 422
    assert api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {}).status_code == 422


def test_reactions_toggle_and_are_validated(api, org, dm):
    mid = api.post(org["emp"], f"/chat/conversations/{dm}/messages", {"body": "React to me"}).json()["id"]
    url = f"/chat/messages/{mid}/reactions"
    one = api.post(org["mgr"], url, {"emoji": "👍"}).json()
    assert one["reactions"] == [{"emoji": "👍", "user_ids": [org["ids"]["mgr"]]}]
    both = api.post(org["emp"], url, {"emoji": "👍"}).json()
    assert both["reactions"][0]["user_ids"] == sorted([org["ids"]["mgr"], org["ids"]["emp"]])
    api.post(org["emp"], url, {"emoji": "❤️"})
    listed = [x for x in api.get(org["mgr"], f"/chat/conversations/{dm}/messages").json()["items"] if x["id"] == mid][0]["reactions"]
    assert {r["emoji"] for r in listed} == {"👍", "❤️"}
    off = api.post(org["mgr"], url, {"emoji": "👍"}).json()                                              # same emoji again takes it back
    assert [r for r in off["reactions"] if r["emoji"] == "👍"][0]["user_ids"] == [org["ids"]["emp"]]
    assert api.post(org["emp"], url, {"emoji": "💩"}).status_code == 422 and api.post(org["emp"], url, {"emoji": ""}).status_code == 422
    assert api.post(org["emp2"], url, {"emoji": "👍"}).status_code == 404                                # outsiders cannot even see the message
    assert api.post(org["emp"], "/chat/messages/987654/reactions", {"emoji": "👍"}).status_code == 404


def test_new_messages_are_pushed_live_with_their_kind(client, api, org, dm):
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": org["mgr"]})
        assert ws.receive_json()["type"] == "ready"
        assert api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {"sticker": "rocket"}).status_code == 201
        pushed = ws.receive_json()
        assert pushed["type"] == "chat" and pushed["data"]["kind"] == "sticker" and pushed["data"]["sticker"]["emoji"] == "🚀"
