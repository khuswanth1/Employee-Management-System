from tests.conftest import PW


def test_dm_between_any_roles_with_live_push_and_unread(client, api, org):
    ids = org["ids"]
    # employee -> HR: get-or-create is idempotent and the other side sees the same conversation
    c1 = api.post(org["emp"], "/chat/conversations", {"user_id": ids["hr"]}).json()
    c2 = api.post(org["emp"], "/chat/conversations", {"user_id": ids["hr"]}).json()
    c3 = api.post(org["hr"], "/chat/conversations", {"user_id": ids["emp"]}).json()
    assert c1["id"] == c2["id"] == c3["id"] and c1["kind"] == "dm"

    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": org["hr"]})
        assert ws.receive_json()["type"] == "ready"
        r = api.post(org["emp"], f"/chat/conversations/{c1['id']}/messages", {"body": "  Hello HR  "})
        assert r.status_code == 201 and r.json()["body"] == "Hello HR"
        pushed = ws.receive_json()
        assert pushed["type"] == "chat" and pushed["data"]["body"] == "Hello HR" and pushed["data"]["sender_id"] == ids["emp"]

    assert api.get(org["hr"], "/chat/unread-count").json()["count"] == 1
    assert api.get(org["emp"], "/chat/unread-count").json()["count"] == 0  # own messages are read
    convs = api.get(org["hr"], "/chat/conversations").json()["items"]
    mine = [c for c in convs if c["id"] == c1["id"]][0]
    assert mine["unread"] == 1 and mine["title"] == api.get(org["emp"], "/auth/me").json()["full_name"] and mine["last_message"]["body"] == "Hello HR"
    assert api.post(org["hr"], f"/chat/conversations/{c1['id']}/read").status_code == 204
    assert api.get(org["hr"], "/chat/unread-count").json()["count"] == 0
    hist = api.get(org["hr"], f"/chat/conversations/{c1['id']}/messages").json()["items"]
    assert [m["body"] for m in hist] == ["Hello HR"]


def test_chat_validation_and_membership(api, org):
    ids = org["ids"]
    dm = api.post(org["emp"], "/chat/conversations", {"user_id": ids["mgr"]}).json()
    # outsiders cannot read, write or mark read (404, no existence leak)
    assert api.get(org["emp2"], f"/chat/conversations/{dm['id']}/messages").status_code == 404
    assert api.post(org["emp2"], f"/chat/conversations/{dm['id']}/messages", {"body": "hi"}).status_code == 404
    assert api.post(org["emp2"], f"/chat/conversations/{dm['id']}/read").status_code == 404
    # validation
    assert api.post(org["emp"], f"/chat/conversations/{dm['id']}/messages", {"body": "   "}).status_code == 422
    assert api.post(org["emp"], f"/chat/conversations/{dm['id']}/messages", {"body": "x" * 4001}).status_code == 422
    me = api.get(org["emp"], "/auth/me").json()["id"]
    assert api.post(org["emp"], "/chat/conversations", {"user_id": me}).status_code == 400
    assert api.post(org["emp"], "/chat/conversations", {"user_id": 99999}).status_code == 400
    assert api.post(org["emp"], "/chat/conversations", {"name": "Empty", "member_ids": []}).status_code == 400
    # directory excludes yourself and supports search
    names = [u["full_name"] for u in api.get(org["emp"], "/chat/users").json()["items"]]
    assert len(names) >= 4 and all(u["id"] != me for u in api.get(org["emp"], "/chat/users").json()["items"])
    assert [u["id"] for u in api.get(org["emp"], "/chat/users?q=mgr2").json()["items"]] == [ids["mgr2"]]


def test_group_chat_fans_out_to_members_only(client, api, org):
    ids = org["ids"]
    g = api.post(org["mgr"], "/chat/conversations", {"name": "Launch crew", "member_ids": [ids["emp"], ids["hr"]]}).json()
    assert g["kind"] == "group" and g["title"] == "Launch crew" and len(g["members"]) == 3
    with client.websocket_connect("/api/v1/ws") as member, client.websocket_connect("/api/v1/ws") as outsider:
        for ws, tok in ((member, org["emp"]), (outsider, org["emp2"])):
            ws.send_json({"type": "auth", "token": tok})
            assert ws.receive_json()["type"] == "ready"
        api.post(org["mgr"], f"/chat/conversations/{g['id']}/messages", {"body": "Kickoff at 10"})
        assert member.receive_json()["data"]["body"] == "Kickoff at 10"
        # the outsider's next frame is the reply to this ping, not the chat message
        outsider.send_json({"type": "ping"})
        assert outsider.receive_json() == {"type": "pong"}
    assert api.get(org["emp2"], "/chat/conversations").json()["items"] == [] or all(
        c["id"] != g["id"] for c in api.get(org["emp2"], "/chat/conversations").json()["items"])


def test_chat_is_tenant_isolated_and_blocks_inactive_peers(api, org):
    api.ensure_company("chatiso")
    fb = api.login("chatiso", "founder@chatiso.com")
    # the other company's user ids overlap ours; they must not resolve across tenants
    emp = api.add_user(fb, "worker@chatiso.com", "manager")  # founder <-> employee DMs are blocked by the hierarchy
    dm = api.post(fb, "/chat/conversations", {"user_id": emp["id"]}).json()
    assert api.get(org["founder"], f"/chat/conversations/{dm['id']}/messages").status_code == 404
    assert all(c["id"] != dm["id"] or c["title"] != emp["full_name"] for c in api.get(org["founder"], "/chat/conversations").json()["items"])
    # offboarded colleague: DM becomes read-only and they leave the directory
    assert api.post(fb, f"/employees/{emp['id']}/offboard").status_code == 200
    assert api.post(fb, f"/chat/conversations/{dm['id']}/messages", {"body": "hello?"}).status_code == 403
    assert emp["id"] not in [u["id"] for u in api.get(fb, "/chat/users").json()["items"]]
