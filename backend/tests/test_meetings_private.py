"""Meetings and calls are private to the host and the people invited (one person, a chosen set, a team or a chat group)."""
import pytest

ROOM = "/api/v1/meetings/ws/"


def make(api, org, who="mgr", **body):
    r = api.post(org[who], "/meetings", {"title": "Planning", **body})
    assert r.status_code == 201, r.text
    return r.json()


def listed(api, org, who):
    return {m["room_id"] for m in api.get(org[who], "/meetings").json()["items"]}


def ws_reason(client, token, room):
    with client.websocket_connect(ROOM + room) as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        return msg.get("reason") or msg["type"]


def test_a_meeting_with_nobody_invited_is_private_to_its_host(api, org, client):
    m = make(api, org)
    assert [(p["id"], p["is_host"]) for p in m["participants"]] == [(org["ids"]["mgr"], True)]
    assert listed(api, org, "mgr") >= {m["room_id"]}
    for who in ("emp", "hr", "founder", "mgr2"):                                   # nobody else, not even HR or the founder
        assert m["room_id"] not in listed(api, org, who), who
        assert api.get(org[who], f"/meetings/{m['room_id']}").status_code == 404, who
        assert ws_reason(client, org[who], m["room_id"]) == "not_found", who       # and the room does not reveal that it exists
    assert ws_reason(client, org["mgr"], m["room_id"]) == "joined"


def test_invite_one_person(api, org, client):
    m = make(api, org, invitee_ids=[org["ids"]["emp"]])
    assert m["invited"] == 1 and m["skipped"] == []
    assert m["room_id"] in listed(api, org, "emp") and m["room_id"] not in listed(api, org, "emp2")
    seen = api.get(org["emp"], f"/meetings/{m['room_id']}").json()
    assert [p["id"] for p in seen["participants"]] == [org["ids"]["mgr"], org["ids"]["emp"]] and seen["is_host"] is False
    assert any("invited you" in n["body"] and n["kind"] == "meeting" for n in api.get(org["emp"], "/notifications").json()["items"])
    assert not any("invited you" in n["body"] for n in api.get(org["emp2"], "/notifications").json()["items"] if "Planning" in n["body"])
    assert ws_reason(client, org["emp"], m["room_id"]) == "joined"
    assert ws_reason(client, org["emp2"], m["room_id"]) == "not_found"


def test_invite_a_chosen_set_of_people(api, org):
    m = make(api, org, "mgr", invitee_ids=[org["ids"]["emp"], org["ids"]["emp2"], org["ids"]["emp"]])   # duplicates are harmless
    assert m["invited"] == 2
    assert {x["id"] for x in m["participants"]} == {org["ids"]["mgr"], org["ids"]["emp"], org["ids"]["emp2"]}
    assert m["room_id"] in listed(api, org, "emp2") and m["room_id"] not in listed(api, org, "mgr2")


def test_invite_a_chat_group_only_if_you_are_in_it(api, org):
    g = api.post(org["mgr"], "/chat/conversations", {"name": "Release crew", "member_ids": [org["ids"]["emp"], org["ids"]["emp2"]]})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    m = make(api, org, "mgr", group_ids=[gid])
    assert m["invited"] == 2 and m["room_id"] in listed(api, org, "emp") and m["room_id"] in listed(api, org, "emp2")
    assert api.post(org["mgr2"], "/meetings", {"title": "Sneaky", "group_ids": [gid]}).status_code == 404       # not their group: it does not exist for them
    assert api.post(org["emp"], "/meetings", {"title": "From the group", "group_ids": [gid]}).json()["invited"] == 2   # a member can use it (mgr + emp2)
    assert api.post(org["mgr"], "/meetings", {"title": "Bad", "group_ids": [99999]}).status_code == 404


def test_invite_a_team_if_you_belong_to_it_or_are_hr(api, org):
    t = api.post(org["founder"], "/teams", {"name": "Mobile", "manager_id": org["ids"]["mgr"], "leader_id": org["ids"]["emp"], "member_ids": [org["ids"]["emp"], org["ids"]["emp2"]]})
    assert t.status_code == 201, t.text
    tid = t.json()["id"]
    m = make(api, org, "emp", team_ids=[tid])                                     # a member invites their team: the others (manager, member) are asked
    assert m["invited"] == 2 and m["room_id"] in listed(api, org, "mgr") and m["room_id"] in listed(api, org, "emp2")
    assert api.post(org["mgr2"], "/meetings", {"title": "Not mine", "team_ids": [tid]}).status_code == 403
    assert api.post(org["hr"], "/meetings", {"title": "HR all-hands for the team", "team_ids": [tid]}).status_code == 201
    assert api.post(org["emp"], "/meetings", {"title": "Bad", "team_ids": [99999]}).status_code == 404


def test_invitations_respect_who_you_may_contact(api, org):
    founder_id = api.get(org["founder"], "/auth/me").json()["id"]
    r = api.post(org["emp"], "/meetings", {"title": "Straight to the top", "invitee_ids": [founder_id]})
    assert r.status_code == 403 and "cannot invite" in r.json()["error"]["message"]        # employee <-> founder is blocked, as in chat
    assert api.post(org["emp"], "/meetings", {"title": "Colleague", "invitee_ids": [org["ids"]["emp2"]]}).status_code == 201
    assert api.post(org["mgr"], "/meetings", {"title": "Ghost", "invitee_ids": [999999]}).status_code == 403
    assert api.post(org["emp"], "/meetings", {"title": "x"}).status_code == 422                      # title too short


def test_people_pulled_in_by_a_group_who_cannot_be_reached_are_left_out_and_reported(api, org):
    founder_id = api.get(org["founder"], "/auth/me").json()["id"]
    g = api.post(org["founder"], "/chat/conversations", {"name": "Leads", "member_ids": [org["ids"]["mgr"], org["ids"]["mgr2"]]}).json()
    api.post(org["founder"], "/meetings", {"title": "Founder with leads", "group_ids": [g["id"]]})
    # a group whose members include someone this host may not contact: they are skipped, the rest are invited
    g2 = api.post(org["mgr"], "/chat/conversations", {"name": "Mixed", "member_ids": [org["ids"]["emp"]]}).json()
    m = api.post(org["mgr"], "/meetings", {"title": "Mixed meeting", "group_ids": [g2["id"]]}).json()
    assert m["invited"] == 1 and founder_id not in {p["id"] for p in m["participants"]}


def test_one_to_one_call(api, org, client):
    r = api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["emp"]})
    assert r.status_code == 201 and r.json()["kind"] == "call" and r.json()["reused"] is False
    room = r.json()["room_id"]
    assert {p["id"] for p in r.json()["participants"]} == {org["ids"]["mgr"], org["ids"]["emp"]}
    note = [n for n in api.get(org["emp"], "/notifications").json()["items"] if n["title"] == "Incoming call"]
    assert note and note[0]["kind"] == "call" and note[0]["link"] == f"/meetings/{room}"
    assert api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["emp"]}).json() == {**api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["emp"]}).json()}
    again = api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["emp"]})
    assert again.json()["reused"] is True and again.json()["room_id"] == room            # ringing twice returns the same call
    assert ws_reason(client, org["emp"], room) == "joined" and ws_reason(client, org["emp2"], room) == "not_found"
    assert api.post(org["mgr"], f"/meetings/{room}/participants", {"invitee_ids": [org["ids"]["emp2"]]}).status_code == 400   # a call stays between two
    assert api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["mgr"]}).status_code in (400, 403)                      # not yourself
    assert api.post(org["mgr"], "/meetings/call", {"user_id": 999999}).status_code == 403
    founder_id = api.get(org["founder"], "/auth/me").json()["id"]
    assert api.post(org["emp"], "/meetings/call", {"user_id": founder_id}).status_code == 403
    api.post(org["mgr"], f"/meetings/{room}/end")
    fresh = api.post(org["mgr"], "/meetings/call", {"user_id": org["ids"]["emp"]}).json()
    assert fresh["reused"] is False and fresh["room_id"] != room                          # a finished call is not reused


def test_the_host_manages_who_is_invited(api, org, client):
    m = make(api, org, invitee_ids=[org["ids"]["emp"]])
    room = m["room_id"]
    assert api.post(org["emp"], f"/meetings/{room}/participants", {"invitee_ids": [org["ids"]["emp2"]]}).status_code == 403    # only the host adds
    assert api.post(org["emp2"], f"/meetings/{room}/participants", {"invitee_ids": [org["ids"]["emp2"]]}).status_code == 404   # a stranger sees nothing
    add = api.post(org["mgr"], f"/meetings/{room}/participants", {"invitee_ids": [org["ids"]["emp2"], org["ids"]["emp"]]})
    assert add.status_code == 200 and add.json()["added"] == 1 and len(add.json()["participants"]) == 3
    assert room in listed(api, org, "emp2")
    assert api.delete(org["emp"], f"/meetings/{room}/participants/{org['ids']['emp2']}").status_code == 403                    # not their call to make
    assert api.delete(org["mgr"], f"/meetings/{room}/participants/{org['ids']['mgr']}").status_code == 400                     # the host stays
    assert api.delete(org["mgr"], f"/meetings/{room}/participants/{org['ids']['hr']}").status_code == 404                      # never invited
    assert api.delete(org["mgr"], f"/meetings/{room}/participants/{org['ids']['emp2']}").status_code == 204
    assert room not in listed(api, org, "emp2") and api.get(org["emp2"], f"/meetings/{room}").status_code == 404
    assert ws_reason(client, org["emp2"], room) == "not_found"                                                                   # and cannot slip back in
    assert api.delete(org["emp"], f"/meetings/{room}/participants/{org['ids']['emp']}").status_code == 204                      # you may leave an invitation
    assert room not in listed(api, org, "emp")


def test_removing_someone_who_is_in_the_room_disconnects_them(api, org, client):
    m = make(api, org, invitee_ids=[org["ids"]["emp"]])
    room = m["room_id"]
    with client.websocket_connect(ROOM + room) as ws:
        ws.send_json({"type": "auth", "token": org["emp"]})
        assert ws.receive_json()["type"] == "joined"
        assert api.delete(org["mgr"], f"/meetings/{room}/participants/{org['ids']['emp']}").status_code == 204
        msgs = []
        try:
            for _ in range(4):
                msgs.append(ws.receive_json())
        except Exception:  # the socket is closed by the server
            pass
        assert {"type": "error", "reason": "removed"} in msgs


def test_ending_a_meeting(api, org):
    m = make(api, org, invitee_ids=[org["ids"]["emp"]])
    room = m["room_id"]
    assert api.post(org["emp"], f"/meetings/{room}/end").status_code == 403                  # invited, but not the host
    assert api.post(org["emp2"], f"/meetings/{room}/end").status_code == 404                 # a stranger learns nothing
    assert api.post(org["founder"], f"/meetings/{room}/end").json()["status"] == "ended"     # moderation by a founder
    assert room not in listed(api, org, "mgr")
    assert api.post(org["mgr"], f"/meetings/{room}/participants", {"invitee_ids": [org["ids"]["emp2"]]}).status_code == 400
    admin_actions = {a["action"] for a in api.get(org["founder"], "/admin/audit-logs?page_size=100").json()["items"]}
    assert {"meeting.created", "meeting.ended_by_admin", "meeting.participant_removed"} <= admin_actions


def test_other_companies_cannot_see_or_join(api, org, client):
    m = make(api, org, invitee_ids=[org["ids"]["emp"]])
    api.ensure_company("meetiso")
    other = api.login("meetiso", "founder@meetiso.com")
    assert api.get(other, f"/meetings/{m['room_id']}").status_code == 404
    assert api.get(other, "/meetings").json()["items"] == []
    assert ws_reason(client, other, m["room_id"]) == "not_found"
    assert api.post(other, f"/meetings/{m['room_id']}/participants", {"invitee_ids": [1]}).status_code == 404
    assert api.post(other, "/meetings/call", {"user_id": org["ids"]["emp"]}).status_code == 403   # that id is not a person in their company
