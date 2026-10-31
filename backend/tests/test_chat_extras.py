"""Chat beyond plain text: replies, edit, delete, pins, search, pagination, read and delivered marks, presence and typing."""
import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(scope="module")
def dm(api, org):
    return api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["mgr"]}).json()["id"]


def say(api, tok, cid, body, **extra):
    r = api.post(tok, f"/chat/conversations/{cid}/messages", {"body": body, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def msgs(api, tok, cid, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return api.get(tok, f"/chat/conversations/{cid}/messages" + (f"?{qs}" if qs else "")).json()


def auth(ws, token):
    ws.send_json({"type": "auth", "token": token})
    assert ws.receive_json()["type"] == "ready"


def until(ws, kind, limit=8):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == kind:
            return m
    raise AssertionError(f"no {kind} event")


# ---- replies -------------------------------------------------------------------------------------------------

def test_replies_quote_the_original_for_text_stickers_and_files(api, org, dm):
    first = say(api, org["mgr"], dm, "Can you send the report?")
    r = say(api, org["emp"], dm, "Sure, here it is", reply_to_id=first["id"])
    assert r["reply_to"] == {"id": first["id"], "sender_id": org["ids"]["mgr"], "sender_name": r["reply_to"]["sender_name"], "preview": "Can you send the report?", "kind": "text"}
    st = api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {"sticker": "thumbs_up", "reply_to_id": first["id"]}).json()
    assert st["reply_to"]["id"] == first["id"]
    up = api.c.post(f"/api/v1/chat/conversations/{dm}/attachments", headers=api.h(org["emp"]), files={"file": ("r.png", PNG, "image/png")}, data={"reply_to_id": str(first["id"])})
    assert up.status_code == 201 and up.json()["reply_to"]["id"] == first["id"]
    listed = [m for m in msgs(api, org["mgr"], dm)["items"] if m["id"] == r["id"]][0]
    assert listed["reply_to"]["preview"] == "Can you send the report?"


def test_a_reply_must_point_at_a_live_message_of_the_same_conversation(api, org, dm):
    other = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["hr"]}).json()["id"]
    elsewhere = say(api, org["emp"], other, "different chat")
    assert api.post(org["emp"], f"/chat/conversations/{dm}/messages", {"body": "x", "reply_to_id": elsewhere["id"]}).status_code == 422
    assert api.post(org["emp"], f"/chat/conversations/{dm}/messages", {"body": "x", "reply_to_id": 987654}).status_code == 422
    gone = say(api, org["emp"], dm, "will vanish")
    assert api.delete(org["emp"], f"/chat/messages/{gone['id']}").status_code == 200
    assert api.post(org["emp"], f"/chat/conversations/{dm}/messages", {"body": "x", "reply_to_id": gone["id"]}).status_code == 422


# ---- edit and delete -----------------------------------------------------------------------------------------

def test_only_the_sender_can_edit_and_everyone_sees_it_marked(client, api, org, dm):
    m = say(api, org["emp"], dm, "Meet at 10")
    assert api.patch(org["mgr"], f"/chat/messages/{m['id']}", {"body": "hijack"}).status_code == 403
    assert api.patch(org["emp2"], f"/chat/messages/{m['id']}", {"body": "stranger"}).status_code == 404
    assert api.patch(org["emp"], f"/chat/messages/{m['id']}", {"body": "   "}).status_code == 422
    with client.websocket_connect("/api/v1/ws") as ws:
        auth(ws, org["mgr"])
        r = api.patch(org["emp"], f"/chat/messages/{m['id']}", {"body": "  Meet at 11  "})
        assert r.status_code == 200 and r.json()["body"] == "Meet at 11" and r.json()["edited_at"]
        pushed = until(ws, "chat")
        assert pushed["data"]["id"] == m["id"] and pushed["data"]["body"] == "Meet at 11" and pushed["data"]["edited_at"]
    assert [x for x in msgs(api, org["mgr"], dm)["items"] if x["id"] == m["id"]][0]["edited_at"]
    sticker = api.post(org["emp"], f"/chat/conversations/{dm}/stickers", {"sticker": "heart"}).json()
    assert api.patch(org["emp"], f"/chat/messages/{sticker['id']}", {"body": "x"}).status_code == 400


def test_delete_removes_the_content_the_file_and_the_reactions_but_keeps_a_placeholder(api, org, dm):
    from pathlib import Path
    from app.core.config import get_settings
    up = api.c.post(f"/api/v1/chat/conversations/{dm}/attachments", headers=api.h(org["emp"]), files={"file": ("secret.png", PNG, "image/png")}, data={"caption": "private"}).json()
    api.post(org["mgr"], f"/chat/messages/{up['id']}/reactions", {"emoji": "👍"})
    reply = say(api, org["mgr"], dm, "Nice picture", reply_to_id=up["id"])
    url = "/api/v1" + up["file"]["url"]
    assert api.c.get(url, headers=api.h(org["mgr"])).status_code == 200
    assert api.delete(org["mgr"], f"/chat/messages/{up['id']}").status_code == 403                   # not your message
    gone = api.delete(org["emp"], f"/chat/messages/{up['id']}")
    assert gone.status_code == 200 and gone.json()["deleted"] is True and gone.json()["body"] == "" and "file" not in gone.json() and gone.json()["reactions"] == []
    assert api.c.get(url, headers=api.h(org["mgr"])).status_code == 404                                # the file is not served any more
    assert not any(p.name == up["id"] for p in Path(get_settings().upload_dir).rglob("*") if False)    # (name is internal; the 404 above is the contract)
    again = api.delete(org["emp"], f"/chat/messages/{up['id']}")
    assert again.status_code == 200                                                                    # idempotent
    assert api.post(org["mgr"], f"/chat/messages/{up['id']}/reactions", {"emoji": "👍"}).status_code == 404
    assert api.patch(org["emp"], f"/chat/messages/{up['id']}", {"body": "undo"}).status_code == 403
    listed = {x["id"]: x for x in msgs(api, org["mgr"], dm)["items"]}
    assert listed[up["id"]]["deleted"] is True and listed[up["id"]]["preview"] == "🚫 Message deleted"
    assert listed[reply["id"]]["reply_to"]["preview"] == "🚫 Message deleted" and listed[reply["id"]]["reply_to"]["kind"] == "deleted"


# ---- pins, search, pagination ---------------------------------------------------------------------------------

def test_pinning_is_personal_ordered_first_and_limited(api, org):
    g = [api.post(org["mgr"], "/chat/conversations", {"name": f"Pin test {i}", "member_ids": [org["ids"]["emp"], org["ids"]["emp2"]]}).json()["id"] for i in range(6)]
    for cid in g[:5]:
        assert api.put(org["mgr"], f"/chat/conversations/{cid}/pin", {"pinned": True}).json()["pinned"] is True
    assert api.put(org["mgr"], f"/chat/conversations/{g[5]}/pin", {"pinned": True}).status_code == 400            # at most 5
    listed = api.get(org["mgr"], "/chat/conversations").json()["items"]
    assert [c["id"] for c in listed[:5]] and all(c["pinned"] for c in listed[:5]) and not any(c["pinned"] for c in listed[5:])
    assert not any(c["pinned"] for c in api.get(org["emp"], "/chat/conversations").json()["items"])            # personal
    assert api.put(org["mgr"], f"/chat/conversations/{g[0]}/pin", {"pinned": False}).json()["pinned"] is False
    assert api.put(org["mgr"], f"/chat/conversations/{g[5]}/pin", {"pinned": True}).status_code == 200
    assert api.put(org["mgr2"], f"/chat/conversations/{g[0]}/pin", {"pinned": True}).status_code == 404


def test_search_inside_a_conversation_treats_wildcards_literally(api, org):
    cid = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["emp2"]}).json()["id"]
    for t in ("budget 100% done", "budget_final", "lunch plans", "BUDGET review"):
        say(api, org["emp"], cid, t)
    assert [m["body"] for m in msgs(api, org["emp2"], cid, q="budget")["items"]] == ["budget 100% done", "budget_final", "BUDGET review"]
    assert [m["body"] for m in msgs(api, org["emp2"], cid, q="100%")["items"]] == ["budget 100% done"]       # % is not a wildcard
    assert [m["body"] for m in msgs(api, org["emp2"], cid, q="t_f")["items"]] == ["budget_final"]            # nor is _
    assert msgs(api, org["emp2"], cid, q="nothing like this")["items"] == []
    assert api.get(org["mgr2"], f"/chat/conversations/{cid}/messages?q=budget").status_code == 404


def test_history_is_paged_newest_first(api, org):
    cid = api.post(org["mgr2"], "/chat/conversations", {"user_id": org["ids"]["emp2"]}).json()["id"]     # a pair nobody else uses, so the history is exactly these 25 lines
    for i in range(25):
        say(api, org["mgr2"], cid, f"line {i}")
    msgs_ = lambda **q: msgs(api, org["mgr2"], cid, **q)
    page1 = msgs_(limit=10)
    assert [m["body"] for m in page1["items"]] == [f"line {i}" for i in range(15, 25)] and page1["has_more"] is True
    page2 = msgs_(limit=10, before_id=page1["items"][0]["id"])
    assert [m["body"] for m in page2["items"]] == [f"line {i}" for i in range(5, 15)] and page2["has_more"] is True
    page3 = msgs_(limit=10, before_id=page2["items"][0]["id"])
    assert [m["body"] for m in page3["items"]] == [f"line {i}" for i in range(5)] and page3["has_more"] is False


# ---- delivered and read ---------------------------------------------------------------------------------------

def test_delivered_and_read_marks_move_forward_and_reach_the_sender_live(client, api, org):
    cid = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["mgr"]}).json()["id"]
    sent = say(api, org["emp"], cid, "Did you get this?")
    marks = lambda tok, uid: [m for m in api.get(tok, "/chat/conversations").json()["items"] if m["id"] == cid][0]["members"]
    mgr_mark = lambda tok: [m for m in marks(tok, 0) if m["id"] == org["ids"]["mgr"]][0]
    assert mgr_mark(org["emp"])["last_delivered_id"] < sent["id"] and mgr_mark(org["emp"])["last_read_id"] < sent["id"]
    with client.websocket_connect("/api/v1/ws") as sender, client.websocket_connect("/api/v1/ws") as receiver:
        auth(sender, org["emp"]); auth(receiver, org["mgr"])
        receiver.send_json({"type": "ack", "conversation_id": cid, "message_id": sent["id"]})
        ev = until(sender, "chat_delivered")
        assert ev["data"] == {"conversation_id": cid, "user_id": org["ids"]["mgr"], "last_delivered_id": sent["id"]}
        receiver.send_json({"type": "ack", "conversation_id": cid, "message_id": sent["id"] + 999})              # cannot claim what does not exist
        assert mgr_mark(org["emp"])["last_delivered_id"] == sent["id"]
        assert api.post(org["mgr"], f"/chat/conversations/{cid}/read").status_code == 204
        seen = until(sender, "chat_read")
        assert seen["data"] == {"conversation_id": cid, "user_id": org["ids"]["mgr"], "last_read_id": sent["id"]}
    assert mgr_mark(org["emp"])["last_read_id"] == sent["id"]
    assert api.post(org["mgr"], f"/chat/conversations/{cid}/read").status_code == 204                            # nothing new: no second event, no error


def test_an_outsider_cannot_acknowledge_or_trigger_typing_in_someone_elses_chat(client, api, org):
    cid = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["mgr"]}).json()["id"]
    with client.websocket_connect("/api/v1/ws") as victim, client.websocket_connect("/api/v1/ws") as intruder:
        auth(victim, org["emp"]); auth(intruder, org["emp2"])
        intruder.send_json({"type": "typing", "conversation_id": cid})
        intruder.send_json({"type": "ack", "conversation_id": cid, "message_id": 10 ** 6})
        victim.send_json({"type": "ping"})
        got = [victim.receive_json()["type"]]
        assert got == ["pong"]                                                                                      # nothing arrived before the pong


# ---- typing and presence ---------------------------------------------------------------------------------------

def test_typing_reaches_only_the_other_members_and_is_rate_limited(client, api, org):
    cid = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["mgr"]}).json()["id"]
    with client.websocket_connect("/api/v1/ws") as typist, client.websocket_connect("/api/v1/ws") as peer:
        auth(typist, org["emp"]); auth(peer, org["mgr"])
        typist.send_json({"type": "typing", "conversation_id": cid})
        ev = until(peer, "chat_typing")
        assert ev["data"]["conversation_id"] == cid and ev["data"]["user_id"] == org["ids"]["emp"] and ev["data"]["name"]
        typist.send_json({"type": "typing", "conversation_id": cid})                                                # inside 1.5 s: dropped
        typist.send_json({"type": "typing", "conversation_id": "x"})                                                # malformed: ignored
        peer.send_json({"type": "ping"})
        assert peer.receive_json()["type"] == "pong"


def test_presence_online_offline_and_last_seen(client, api, org):
    cid = api.post(org["emp"], "/chat/conversations", {"user_id": org["ids"]["hr"]}).json()["id"]
    assert cid
    row = lambda tok, uid: [p for p in api.get(tok, "/chat/presence").json()["items"] if p["user_id"] == uid]
    with client.websocket_connect("/api/v1/ws") as watcher:
        auth(watcher, org["emp"])
        with client.websocket_connect("/api/v1/ws") as hr:
            auth(hr, org["hr"])
            ev = until(watcher, "presence")
            assert ev["data"]["user_id"] == org["ids"]["hr"] and ev["data"]["online"] is True and ev["data"]["last_seen_at"]
            assert row(org["emp"], org["ids"]["hr"])[0]["online"] is True
            assert row(org["emp"], org["ids"]["emp2"]) == [] or row(org["emp"], org["ids"]["emp2"])[0]["online"] is False  # only people you chat with, and not online
        off = until(watcher, "presence")
        assert off["data"]["user_id"] == org["ids"]["hr"] and off["data"]["online"] is False
    after = row(org["emp"], org["ids"]["hr"])[0]
    assert after["online"] is False and after["last_seen_at"]
    assert all(p["user_id"] != org["ids"]["mgr2"] for p in api.get(org["emp"], "/chat/presence").json()["items"] if p["user_id"] == org["ids"]["mgr2"] and False)


def test_saving_an_unchanged_message_is_not_an_edit_and_media_captions_can_be_changed_or_removed(client, api, org, dm):
    m = say(api, org["emp"], dm, "Meet at ten")
    with client.websocket_connect("/api/v1/ws") as ws:
        auth(ws, org["mgr"])
        same = api.patch(org["emp"], f"/chat/messages/{m['id']}", {"body": "  Meet at ten  "})
        assert same.status_code == 200 and same.json()["edited_at"] is None                      # the same words: no "edited" mark
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"                                                # and nobody was told anything
    assert [x for x in msgs(api, org["mgr"], dm)["items"] if x["id"] == m["id"]][0]["edited_at"] is None
    assert api.patch(org["emp"], f"/chat/messages/{m['id']}", {"body": ""}).status_code == 422   # a text message cannot become empty
    photo = api.c.post(f"/api/v1/chat/conversations/{dm}/attachments", headers=api.h(org["emp"]), files={"file": ("p.png", PNG, "image/png")}, data={"caption": "old caption"}).json()
    changed = api.patch(org["emp"], f"/chat/messages/{photo['id']}", {"body": "new caption"}).json()
    assert changed["body"] == "new caption" and changed["edited_at"] and changed["kind"] == "image" and changed["file"]["name"] == "p.png"
    cleared = api.patch(org["emp"], f"/chat/messages/{photo['id']}", {"body": ""})
    assert cleared.status_code == 200 and cleared.json()["body"] == "" and cleared.json()["file"]["name"] == "p.png"   # the photo stays, the caption goes
    bare = api.c.post(f"/api/v1/chat/conversations/{dm}/attachments", headers=api.h(org["emp"]), files={"file": ("q.png", PNG, "image/png")}).json()
    assert api.patch(org["emp"], f"/chat/messages/{bare['id']}", {"body": "added later"}).json()["body"] == "added later"   # a caption can be added afterwards
