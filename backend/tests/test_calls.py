"""One-to-one calls: ringing, answering, declining, missed calls and the call history."""
import time

import pytest

from app.modules.meetings import router as meetings

ROOM = "/api/v1/meetings/ws/"


def auth(ws, token):
    ws.send_json({"type": "auth", "token": token})
    assert ws.receive_json()["type"] == "ready"


def until(ws, kind, limit=8):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == kind:
            return m
    raise AssertionError(f"no {kind} event")


def place(api, tok, to, video=True):
    r = api.post(tok, "/meetings/call", {"user_id": to, "video": video})
    assert r.status_code == 201, r.text
    return r.json()


def history(api, tok):
    return api.get(tok, "/meetings/calls/history").json()["items"]


def notes(api, tok, title):
    return [n for n in api.get(tok, "/notifications").json()["items"] if n["title"] == title]


def test_a_call_rings_the_other_person_live_with_voice_or_video(client, api, org):
    callee = org["ids"]["hr"]
    with client.websocket_connect("/api/v1/ws") as ws:
        auth(ws, org["hr"])
        voice = place(api, org["mgr"], callee, video=False)
        ring = until(ws, "call")["data"]
        assert ring == {"room_id": voice["room_id"], "from_id": org["ids"]["mgr"], "from_name": ring["from_name"], "video": False}
        assert voice["call_video"] is False and voice["outcome"] is None
        again = api.post(org["mgr"], "/meetings/call", {"user_id": callee, "video": False}).json()
        assert again["reused"] is True and again["room_id"] == voice["room_id"]
        assert until(ws, "call")["data"]["room_id"] == voice["room_id"]                                    # ringing again, same call
    api.post(org["mgr"], f"/meetings/{voice['room_id']}/end")


def test_declining_ends_the_call_tells_the_caller_and_is_recorded(client, api, org):
    c = place(api, org["mgr"], org["ids"]["emp"])
    assert api.post(org["mgr"], f"/meetings/{c['room_id']}/decline").status_code == 403                       # the caller cannot decline their own call
    assert api.post(org["emp2"], f"/meetings/{c['room_id']}/decline").status_code == 404                      # a stranger cannot even see it
    with client.websocket_connect("/api/v1/ws") as caller:
        auth(caller, org["mgr"])
        r = api.post(org["emp"], f"/meetings/{c['room_id']}/decline")
        assert r.status_code == 200 and r.json()["outcome"] == "declined" and r.json()["status"] == "ended"
        assert until(caller, "call_ended")["data"] == {"room_id": c["room_id"], "outcome": "declined"}
    assert api.post(org["emp"], f"/meetings/{c['room_id']}/decline").status_code == 409                       # only once
    out = [h for h in history(api, org["mgr"]) if h["room_id"] == c["room_id"]][0]
    inc = [h for h in history(api, org["emp"]) if h["room_id"] == c["room_id"]][0]
    assert out["direction"] == "outgoing" and out["outcome"] == "declined" and out["peer"]["id"] == org["ids"]["emp"]
    assert inc["direction"] == "incoming" and inc["outcome"] == "declined" and inc["peer"]["id"] == org["ids"]["mgr"]
    with client.websocket_connect(ROOM + c["room_id"]) as ws:                                                  # a declined call cannot be joined later
        ws.send_json({"type": "auth", "token": org["emp"]})
        assert ws.receive_json() == {"type": "error", "reason": "ended"}


def test_answering_marks_it_answered_silences_other_devices_and_is_timed(client, api, org):
    c = place(api, org["mgr"], org["ids"]["emp2"])
    with client.websocket_connect("/api/v1/ws") as other_device, client.websocket_connect(ROOM + c["room_id"]) as callee:
        auth(other_device, org["emp2"])
        callee.send_json({"type": "auth", "token": org["emp2"]})
        assert callee.receive_json()["type"] == "joined"
        done = until(other_device, "call_ended")["data"]
        assert done == {"room_id": c["room_id"], "outcome": "answered"}                                      # other tabs stop ringing
        time.sleep(1.1)
    ended = api.post(org["mgr"], f"/meetings/{c['room_id']}/end").json()
    assert ended["outcome"] == "answered" and ended["answered_at"] and ended["ended_at"]
    h = [x for x in history(api, org["emp2"]) if x["room_id"] == c["room_id"]][0]
    assert h["outcome"] == "answered" and h["duration_s"] >= 1 and h["direction"] == "incoming"
    assert notes(api, org["emp2"], "Missed call") == [] or all(c["room_id"] not in (n["link"] or "") for n in notes(api, org["emp2"], "Missed call"))


def test_hanging_up_before_anyone_answers_is_a_missed_call_with_a_notification(client, api, org):
    c = place(api, org["mgr"], org["ids"]["emp"])
    with client.websocket_connect("/api/v1/ws") as callee:
        auth(callee, org["emp"])
        assert api.post(org["mgr"], f"/meetings/{c['room_id']}/end").json()["outcome"] == "missed"
        assert until(callee, "call_ended")["data"]["outcome"] == "missed"                                    # their ringing stops
    assert [n for n in notes(api, org["emp"], "Missed call") if "tried to call you" in n["body"]]
    assert [h for h in history(api, org["emp"]) if h["room_id"] == c["room_id"]][0]["outcome"] == "missed"


def test_closing_the_page_while_ringing_also_counts_as_missed(client, api, org):
    c = place(api, org["mgr"], org["ids"]["emp"])
    with client.websocket_connect(ROOM + c["room_id"]) as host:
        host.send_json({"type": "auth", "token": org["mgr"]})
        assert host.receive_json()["type"] == "joined"
    deadline = time.time() + 5
    while time.time() < deadline and api.get(org["mgr"], f"/meetings/{c['room_id']}").json()["status"] != "ended":
        time.sleep(0.1)
    m = api.get(org["mgr"], f"/meetings/{c['room_id']}").json()
    assert m["status"] == "ended" and m["outcome"] == "missed"


def test_a_ring_nobody_answers_becomes_missed_on_its_own(api, org, monkeypatch):
    monkeypatch.setattr(meetings, "RING_SECONDS", 0)
    c = place(api, org["mgr"], org["ids"]["emp2"])
    time.sleep(0.05)
    h = [x for x in history(api, org["mgr"]) if x["room_id"] == c["room_id"]][0]                              # reading the history settles it
    assert h["outcome"] == "missed"
    assert api.get(org["mgr"], f"/meetings/{c['room_id']}").json()["status"] == "ended"
    fresh = place(api, org["mgr"], org["ids"]["emp2"])                                                         # and the next call is a new one
    assert fresh["room_id"] != c["room_id"] and fresh["reused"] is False
    monkeypatch.setattr(meetings, "RING_SECONDS", 60)
    api.post(org["mgr"], f"/meetings/{fresh['room_id']}/end")


def test_history_is_private_paged_and_covers_calls_only(api, org):
    for _ in range(3):
        c = place(api, org["mgr"], org["ids"]["hr"])
        api.post(org["mgr"], f"/meetings/{c['room_id']}/end")
    mine = api.get(org["mgr"], "/meetings/calls/history?limit=2").json()
    assert len(mine["items"]) == 2 and mine["has_more"] is True
    older = api.get(org["mgr"], f"/meetings/calls/history?limit=50&before_id={mine['items'][-1]['id']}").json()["items"]
    assert all(h["id"] < mine["items"][-1]["id"] for h in older)
    assert history(api, org["mgr2"]) == [] or all(h["peer"]["id"] != org["ids"]["hr"] for h in history(api, org["mgr2"]))
    meeting = api.post(org["mgr"], "/meetings", {"title": "Not a call", "invitee_ids": [org["ids"]["emp"]]}).json()
    assert all(h["room_id"] != meeting["room_id"] for h in history(api, org["mgr"]))
    assert api.get(org["mgr"], "/meetings/calls/history?limit=0").status_code == 422
    api.ensure_company("callcross")
    assert history(api, api.login("callcross", "founder@callcross.com")) == []


def test_a_voice_call_placed_while_an_unanswered_video_call_is_open_rings_as_voice(client, api, org):
    callee = org["ids"]["emp"]
    first = place(api, org["mgr"], callee, video=True)
    assert first["call_video"] is True
    with client.websocket_connect("/api/v1/ws") as ws:
        auth(ws, org["emp"])
        again = api.post(org["mgr"], "/meetings/call", {"user_id": callee, "video": False}).json()
        assert again["reused"] is True and again["room_id"] == first["room_id"] and again["call_video"] is False
        assert until(ws, "call")["data"]["video"] is False                       # the other person is rung for a voice call
    again = api.post(org["mgr"], "/meetings/call", {"user_id": callee, "video": True}).json()
    assert again["call_video"] is True                                           # and back to video if that is what is asked now
    api.post(org["mgr"], f"/meetings/{first['room_id']}/end")


def test_the_notification_link_of_a_voice_call_opens_it_as_a_voice_call(api, org):
    voice = place(api, org["mgr"], org["ids"]["emp2"], video=False)
    link = [n for n in notes(api, org["emp2"], "Incoming call") if voice["room_id"] in (n["link"] or "")][0]["link"]
    assert link == f"/meetings/{voice['room_id']}?audio=1"
    api.post(org["mgr"], f"/meetings/{voice['room_id']}/end")
    video = place(api, org["mgr"], org["ids"]["emp2"], video=True)
    assert [n for n in notes(api, org["emp2"], "Incoming call") if video["room_id"] in (n["link"] or "")][0]["link"] == f"/meetings/{video['room_id']}"
    api.post(org["mgr"], f"/meetings/{video['room_id']}/end")
