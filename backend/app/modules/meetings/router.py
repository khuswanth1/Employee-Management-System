"""Meetings and calls.

A meeting is private to its host and the people invited: one person (a call), a hand-picked set, or whole teams / chat groups
that the host belongs to. Nobody else can see it in their list, read its details, or join its signaling room (the room id alone
is not enough). Invitations follow the same hierarchy as chat (`access.can_message`), so the meeting never lets someone reach a
person they could not message. HR / founders may end any meeting (moderation) but do not get to join one they were not invited to.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import anyio.from_thread
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.access import can_message
from app.common import audit
from app.core.config import get_settings
from app.core.errors import AppError, Forbidden, NotFound
from app.db.tenant_models import CommException, Conversation, ConversationMember, Meeting, MeetingParticipant, Team, TeamMember, User
from app.db.base import utcnow
from app.deps import Ctx, get_ctx
from app.modules.notifications.router import authenticate_ws, watch_session
from app.modules.notifications.service import notify
from app.realtime import publish_threadsafe, rooms
from app.tenancy.manager import tenants

log = logging.getLogger("worksphere.meetings")
router = APIRouter(prefix="/meetings", tags=["meetings"])
MAX_SIGNAL_BYTES = 64 * 1024
RELAY_TYPES = {"offer", "answer", "ice"}
MAX_INVITEES = 100
RING_SECONDS = 60  # a call nobody picked up within this long counts as missed (the page itself gives up after 45 s)


class Audience(BaseModel):
    invitee_ids: list[int] = Field(default_factory=list, max_length=MAX_INVITEES)
    team_ids: list[int] = Field(default_factory=list, max_length=20)   # every member of these teams (you must belong to them, or be HR / a founder)
    group_ids: list[int] = Field(default_factory=list, max_length=20)  # every member of these chat groups (you must be in them)


class MeetingIn(Audience):
    title: str = Field(min_length=2, max_length=200)
    scheduled_at: datetime | None = None


class CallIn(BaseModel):
    user_id: int
    video: bool = True  # False = a voice call


def ser(m: Meeting, me: int | None = None) -> dict:
    return {"id": m.id, "title": m.title, "room_id": m.room_id, "host_id": m.host_id, "scheduled_at": m.scheduled_at, "status": m.status, "kind": m.kind,
            "created_at": m.created_at, "is_host": (me == m.host_id) if me is not None else None,
            "call_video": m.call_video, "outcome": m.outcome, "answered_at": m.answered_at, "ended_at": m.ended_at}


def _people(ctx: Ctx, m: Meeting) -> list[dict]:
    ids = [m.host_id, *[p.user_id for p in m.participants]]
    users = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))}
    return [{"id": i, "name": users[i].full_name, "avatar_v": users[i].avatar_name, "is_host": i == m.host_id} for i in dict.fromkeys(ids) if i in users]


def _expand(ctx: Ctx, aud: Audience) -> tuple[list[User], list[dict]]:
    """Resolve people + teams + groups into the people the caller may actually invite. Returns (users, skipped)."""
    wanted: set[int] = set(aud.invitee_ids)
    for tid in aud.team_ids:
        t = ctx.db.get(Team, tid)
        if t is None:
            raise NotFound("Team not found")
        members = set(ctx.db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == tid)))
        if ctx.role not in ("hr", "founder") and ctx.user.id not in members | {t.leader_id, t.manager_id}:
            raise Forbidden("You can only invite a team you belong to")
        wanted |= members | {x for x in (t.leader_id, t.manager_id) if x}
    for gid in aud.group_ids:
        conv = ctx.db.get(Conversation, gid)
        member_ids = set(ctx.db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == gid))) if conv else set()
        if conv is None or conv.kind != "group" or ctx.user.id not in member_ids:
            raise NotFound("Group not found")
        wanted |= member_ids
    wanted.discard(ctx.user.id)
    if len(wanted) > MAX_INVITEES:
        raise AppError(f"A meeting can have at most {MAX_INVITEES} invited people")
    exc = set(ctx.db.scalars(select(CommException.user_id)))
    ok: list[User] = []
    skipped: list[dict] = []
    found = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_(wanted)))} if wanted else {}
    for uid in sorted(wanted):
        u = found.get(uid)
        if u is None or not u.is_active:
            skipped.append({"id": uid, "name": u.full_name if u else None, "reason": "not available"})
        elif not can_message(ctx.user, u, exceptions=exc):
            skipped.append({"id": uid, "name": u.full_name, "reason": "you cannot contact this person"})
        else:
            ok.append(u)
    # an explicitly chosen person who cannot be reached is an error; people pulled in by a team or group are simply left out
    explicit_bad = [s for s in skipped if s["id"] in set(aud.invitee_ids)]
    if explicit_bad:
        raise Forbidden(f"You cannot invite {explicit_bad[0]['name'] or 'this person'}: " + explicit_bad[0]["reason"])
    return ok, skipped


def _add(ctx: Ctx, m: Meeting, users: list[User], announce: str) -> list[User]:
    have = {p.user_id for p in m.participants}
    new = [u for u in users if u.id not in have and u.id != m.host_id]
    for u in new:
        m.participants.append(MeetingParticipant(user_id=u.id, invited_by=ctx.user.id))
    if new:
        when = f" at {m.scheduled_at:%Y-%m-%d %H:%M} UTC" if m.scheduled_at else ""
        notify(ctx.db, [u.id for u in new], "Incoming call" if m.kind == "call" else "Meeting invitation", f"{ctx.user.full_name} {announce} “{m.title}”{when}",
               "call" if m.kind == "call" else "meeting", f"/meetings/{m.room_id}" + ("?audio=1" if m.kind == "call" and not m.call_video else ""))
    return new


def _visible(ctx: Ctx, m: Meeting | None) -> Meeting:
    """The meeting, only if the caller is its host or an invited person. Anyone else gets 404, as if it did not exist."""
    if m is None or not (m.host_id == ctx.user.id or any(p.user_id == ctx.user.id for p in m.participants)):
        raise NotFound("Meeting not found")
    return m


def _by_room(ctx: Ctx, room_id: str) -> Meeting | None:
    return ctx.db.scalar(select(Meeting).where(Meeting.room_id == room_id))


@router.post("", status_code=201)
def create(body: MeetingIn, ctx: Ctx = Depends(get_ctx)):
    users, skipped = _expand(ctx, body)
    m = Meeting(title=body.title.strip(), room_id=secrets.token_urlsafe(12), host_id=ctx.user.id, scheduled_at=body.scheduled_at)
    ctx.db.add(m)
    ctx.db.flush()
    _add(ctx, m, users, "invited you to")
    audit(ctx, "meeting.created", "meeting", m.id, {"invited": len(users)})
    ctx.db.commit()
    return {**ser(m, ctx.user.id), "invited": len(users), "skipped": skipped, "participants": _people(ctx, m)}


@router.post("/call", status_code=201)
def call(body: CallIn, ctx: Ctx = Depends(get_ctx)):
    """Start a one-to-one call: a private meeting with exactly one other person, who is notified at once. Calling the same person
    again while a call between you two is still open returns that call instead of ringing twice."""
    users, _ = _expand(ctx, Audience(invitee_ids=[body.user_id]))
    if not users:
        raise AppError("Choose someone to call")
    other = users[0]
    _expire_unanswered(ctx)
    for c in ctx.db.scalars(select(Meeting).where(Meeting.kind == "call", Meeting.host_id == ctx.user.id, Meeting.status != "ended").order_by(Meeting.id.desc())):
        if [p.user_id for p in c.participants] == [other.id]:
            if c.outcome is None:  # still ringing: ring again (it may have been missed on their screen), as the kind of call asked for now
                c.call_video = body.video
                _ring(ctx, c, other.id)
            ctx.db.commit()
            return {**ser(c, ctx.user.id), "reused": True, "participants": _people(ctx, c)}
    m = Meeting(title=f"Call: {ctx.user.full_name} & {other.full_name}", room_id=secrets.token_urlsafe(12), host_id=ctx.user.id, kind="call", call_video=body.video)
    ctx.db.add(m)
    ctx.db.flush()
    _add(ctx, m, [other], "is calling you:")
    _ring(ctx, m, other.id)
    audit(ctx, "meeting.call_started", "meeting", m.id, {"to": other.id, "video": body.video})
    ctx.db.commit()
    return {**ser(m, ctx.user.id), "reused": False, "participants": _people(ctx, m)}


def _ring(ctx: Ctx, m: Meeting, callee_id: int) -> None:
    """Live "incoming call" for the other person's open pages (the persisted notification is separate)."""
    ctx.db.info.setdefault("push", []).append(([callee_id], {"type": "call", "data": {
        "room_id": m.room_id, "from_id": ctx.user.id, "from_name": ctx.user.full_name, "video": m.call_video}}))


def _finish_call(db, m: Meeting, outcome: str | None, now: datetime) -> list:
    """Closes a call and records how it went; returns the events to push (the caller sends them after commit)."""
    m.status, m.ended_at = "ended", now
    if outcome and m.outcome is None:
        m.outcome = outcome
    events = []
    callee = [p.user_id for p in m.participants]
    if m.kind == "call" and m.outcome in ("missed", "declined"):
        events.append((callee + [m.host_id], {"type": "call_ended", "data": {"room_id": m.room_id, "outcome": m.outcome}}))
    return events


def _expire_unanswered(ctx: Ctx) -> None:
    """Calls nobody answered within RING_SECONDS become missed calls (this also covers a caller who simply closed the page)."""
    cutoff = utcnow() - timedelta(seconds=RING_SECONDS)
    mine = select(MeetingParticipant.meeting_id).where(MeetingParticipant.user_id == ctx.user.id)
    stale = ctx.db.scalars(select(Meeting).where(Meeting.kind == "call", Meeting.status != "ended", Meeting.outcome.is_(None), Meeting.created_at < cutoff,
                                                 or_(Meeting.host_id == ctx.user.id, Meeting.id.in_(mine))))
    for m in stale:
        for ids, ev in _finish_call(ctx.db, m, "missed", utcnow()):
            ctx.db.info.setdefault("push", []).append((ids, ev))
        host = ctx.db.get(User, m.host_id)
        notify(ctx.db, [p.user_id for p in m.participants], "Missed call", f"{host.full_name if host else 'Someone'} tried to call you", "call", "/chat")


@router.post("/{room_id}/decline")
def decline(room_id: str, ctx: Ctx = Depends(get_ctx)):
    """The person being called says no. The call ends, the caller is told, and it is recorded as declined."""
    m = _visible(ctx, _by_room(ctx, room_id))
    if m.kind != "call" or m.host_id == ctx.user.id:
        raise Forbidden("Only the person being called can decline a call")
    if m.status == "ended" or m.outcome is not None:
        raise AppError("This call has already ended", status_code=409)
    for ids, ev in _finish_call(ctx.db, m, "declined", utcnow()):
        ctx.db.info.setdefault("push", []).append((ids, ev))
    audit(ctx, "meeting.call_declined", "meeting", m.id)
    ctx.db.commit()
    return ser(m, ctx.user.id)


@router.get("/calls/history")
def call_history(limit: int = Query(30, ge=1, le=100), before_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    """Your calls, newest first: who, which direction, voice or video, how it ended and how long you talked."""
    _expire_unanswered(ctx)
    ctx.db.commit()
    mine = select(MeetingParticipant.meeting_id).where(MeetingParticipant.user_id == ctx.user.id)
    stmt = select(Meeting).where(Meeting.kind == "call", or_(Meeting.host_id == ctx.user.id, Meeting.id.in_(mine))).order_by(Meeting.id.desc()).limit(limit)
    if before_id:
        stmt = stmt.where(Meeting.id < before_id)
    rows = list(ctx.db.scalars(stmt))
    people = {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_({m.host_id for m in rows} | {p.user_id for m in rows for p in m.participants})))} if rows else {}
    items = []
    for m in rows:
        outgoing = m.host_id == ctx.user.id
        peer_id = next((p.user_id for p in m.participants), None) if outgoing else m.host_id
        peer = people.get(peer_id)
        talked = int((m.ended_at - m.answered_at).total_seconds()) if m.answered_at and m.ended_at else None
        items.append({"id": m.id, "room_id": m.room_id, "direction": "outgoing" if outgoing else "incoming", "video": m.call_video, "outcome": m.outcome or ("ringing" if m.status != "ended" else "missed"),
                      "peer": {"id": peer.id, "name": peer.full_name, "avatar_v": peer.avatar_name} if peer else None, "started_at": m.created_at, "duration_s": talked})
    return {"items": items, "has_more": len(rows) == limit}


@router.get("")
def list_meetings(ctx: Ctx = Depends(get_ctx)):
    """Meetings you host or are invited to (not ended), newest first."""
    mine = select(MeetingParticipant.meeting_id).where(MeetingParticipant.user_id == ctx.user.id)
    rows = ctx.db.scalars(select(Meeting).where(Meeting.status != "ended", or_(Meeting.host_id == ctx.user.id, Meeting.id.in_(mine))).order_by(Meeting.id.desc()).limit(50)).all()
    return {"items": [{**ser(m, ctx.user.id), "participants": _people(ctx, m)} for m in rows]}


@router.get("/ice-config")
def ice_config(ctx: Ctx = Depends(get_ctx)):
    """STUN always; TURN with short-lived HMAC credentials (coturn use-auth-secret) when configured."""
    s = get_settings()
    servers: list[dict] = [{"urls": [u.strip() for u in s.stun_urls.split(",") if u.strip()]}] if s.stun_urls else []
    if s.turn_url:
        urls = [u.strip() for u in s.turn_url.split(",") if u.strip()]
        if s.turn_secret:
            username = f"{int(time.time()) + 3600}:{ctx.company_id}-{ctx.user.id}"
            cred = base64.b64encode(hmac.new(s.turn_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
            servers.append({"urls": urls, "username": username, "credential": cred})
        elif s.turn_username:
            servers.append({"urls": urls, "username": s.turn_username, "credential": s.turn_credential})
    return {"iceServers": servers}


@router.get("/{room_id}")
def get_meeting(room_id: str, ctx: Ctx = Depends(get_ctx)):
    m = _visible(ctx, _by_room(ctx, room_id))
    return {**ser(m, ctx.user.id), "participants": _people(ctx, m)}


@router.post("/{room_id}/participants")
def add_participants(room_id: str, body: Audience, ctx: Ctx = Depends(get_ctx)):
    """The host invites more people (individuals, teams, groups) to a meeting that has not ended."""
    m = _visible(ctx, _by_room(ctx, room_id))
    if m.host_id != ctx.user.id:
        raise Forbidden("Only the host can invite people")
    if m.status == "ended":
        raise AppError("This meeting has ended")
    if m.kind == "call":
        raise AppError("A one-to-one call has exactly two people. Start a meeting to include more.")
    users, skipped = _expand(ctx, body)
    if len(m.participants) + len(users) > MAX_INVITEES:
        raise AppError(f"A meeting can have at most {MAX_INVITEES} invited people")
    new = _add(ctx, m, users, "invited you to")
    audit(ctx, "meeting.invited", "meeting", m.id, {"added": len(new)})
    ctx.db.commit()
    return {"added": len(new), "skipped": skipped, "participants": _people(ctx, m)}


@router.delete("/{room_id}/participants/{user_id}", status_code=204)
def remove_participant(room_id: str, user_id: int, ctx: Ctx = Depends(get_ctx)):
    """The host removes someone (they are disconnected if they are in the room), or an invited person leaves the invitation."""
    m = _visible(ctx, _by_room(ctx, room_id))
    if user_id != ctx.user.id and m.host_id != ctx.user.id:
        raise Forbidden("Only the host can remove people")
    if user_id == m.host_id:
        raise AppError("The host cannot be removed; end the meeting instead")
    row = next((p for p in m.participants if p.user_id == user_id), None)
    if row is None:
        raise NotFound("That person is not in this meeting")
    m.participants.remove(row)
    audit(ctx, "meeting.participant_removed", "meeting", m.id, {"user_id": user_id})
    ctx.db.commit()
    try:
        anyio.from_thread.run(rooms.kick_user, ctx.company_id, room_id, user_id)
    except Exception:  # noqa: BLE001 - not connected, or no event loop: they simply cannot rejoin
        pass


@router.post("/{room_id}/end")
def end(room_id: str, ctx: Ctx = Depends(get_ctx)):
    m = _by_room(ctx, room_id)
    if m is None:
        raise NotFound("Meeting not found")
    if m.host_id != ctx.user.id and ctx.role not in ("founder", "hr"):
        if any(p.user_id == ctx.user.id for p in m.participants):
            raise Forbidden("Only the host can end the meeting")
        raise NotFound("Meeting not found")
    was_open = m.status != "ended"
    unanswered = m.kind == "call" and m.outcome is None
    for ids, ev in _finish_call(ctx.db, m, "missed" if unanswered else None, utcnow()) if was_open else []:
        ctx.db.info.setdefault("push", []).append((ids, ev))
    if was_open and unanswered:  # the caller hung up before anyone picked up
        notify(ctx.db, [p.user_id for p in m.participants], "Missed call", f"{ctx.user.full_name} tried to call you", "call", "/chat")
    if m.host_id != ctx.user.id:
        audit(ctx, "meeting.ended_by_admin", "meeting", m.id)
    ctx.db.commit()
    return ser(m, ctx.user.id)


def _activate(company, room_id: str, user_id: int) -> str | None:
    """Returns None if this person may join, else a reason. Marks a scheduled meeting active."""
    with tenants.session_for(company) as db:
        m = db.scalar(select(Meeting).where(Meeting.room_id == room_id))
        if m is None:
            return "not_found"
        if m.host_id != user_id and not any(p.user_id == user_id for p in m.participants):
            return "not_found"  # same answer as a room that does not exist: invitations are not guessable by probing
        if m.status == "ended":
            return "ended"
        if m.status == "scheduled":
            m.status = "active"
        if m.kind == "call" and m.host_id != user_id and m.outcome is None:  # the callee joined: the call is answered
            m.outcome, m.answered_at = "answered", datetime.now(timezone.utc)
            publish_threadsafe(company.id, [p.user_id for p in m.participants] + [m.host_id], {"type": "call_ended", "data": {"room_id": m.room_id, "outcome": "answered"}})
        db.commit()
        return None


def _close_empty_call(company, room_id: str) -> None:
    """When the last person leaves a call the call is over: an answered call is timed, an unanswered one is a missed call."""
    with tenants.session_for(company) as db:
        m = db.scalar(select(Meeting).where(Meeting.room_id == room_id))
        if m is None or m.kind != "call" or m.status == "ended":
            return
        now = datetime.now(timezone.utc)
        unanswered = m.outcome is None
        for ids, ev in _finish_call(db, m, "missed" if unanswered else None, now):
            publish_threadsafe(company.id, ids, ev)
        if unanswered:
            host = db.get(User, m.host_id)
            notify(db, [p.user_id for p in m.participants], "Missed call", f"{host.full_name if host else 'Someone'} tried to call you", "call", "/chat")
        db.commit()


@router.websocket("/ws/{room_id}")
async def signaling(websocket: WebSocket, room_id: str):
    """WebRTC signaling relay. Rooms are namespaced by tenant and only the host and invited people may enter."""
    auth = await authenticate_ws(websocket)
    if auth is None:
        return
    company, user = auth
    problem = await run_in_threadpool(_activate, company, room_id, user.id)
    if problem:
        await websocket.send_json({"type": "error", "reason": problem})
        await websocket.close(code=4404)
        return
    peer_id = uuid.uuid4().hex[:12]
    existing = await rooms.join(company.id, room_id, peer_id, websocket, user.full_name, user.id)
    if existing is None:
        await websocket.send_json({"type": "error", "reason": "room_full"})
        await websocket.close(code=4409)
        return
    watcher = watch_session(websocket)
    await websocket.send_json({"type": "joined", "peer_id": peer_id, "peers": existing})
    await rooms.broadcast(company.id, room_id, {"type": "peer-joined", "peer_id": peer_id, "name": user.full_name}, exclude=peer_id)
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_SIGNAL_BYTES:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind in RELAY_TYPES and isinstance(msg.get("to"), str):
                await rooms.send(company.id, room_id, msg["to"], {"type": kind, "from": peer_id, "data": msg.get("data")})
            elif kind in ("screen-share", "mute"):
                await rooms.broadcast(company.id, room_id, {"type": kind, "from": peer_id, "active": bool(msg.get("active"))}, exclude=peer_id)
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()
        await rooms.leave(company.id, room_id, peer_id)
        await rooms.broadcast(company.id, room_id, {"type": "peer-left", "peer_id": peer_id})
        if not rooms.rooms.get((company.id, room_id)):
            try:
                await run_in_threadpool(_close_empty_call, company, room_id)
            except Exception:  # noqa: BLE001 - housekeeping must never break the socket teardown
                log.exception("could not close the empty call")
