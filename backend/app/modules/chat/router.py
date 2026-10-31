"""Company-scoped chat: direct messages and groups between any users of the same company.

Messages are persisted, then pushed over the existing /ws socket after the request commits
(db.info["push"], see deps.get_ctx). The tenant database is the isolation boundary: a user can only
ever see conversations they are a member of.
"""
from itertools import combinations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app import storage
from app.access import can_message
from app.common import audit
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.notifications.service import notify
from app.db.base import utcnow
from app.db.tenant_models import CommException, Conversation, ConversationMember, Message, MessageReaction, User
from app.deps import Ctx, get_ctx, require_roles
from app.realtime import manager

router = APIRouter(prefix="/chat", tags=["chat"])
MAX_GROUP = 50

# Stickers are a fixed, server-validated set (the client only draws what the server lists, so nothing arbitrary can be sent as one).
STICKERS = {
    "thumbs_up": ("👍", "Thumbs up", "Reactions"), "heart": ("❤️", "Love", "Reactions"), "laugh": ("😂", "Laughing", "Reactions"), "wow": ("😮", "Wow", "Reactions"),
    "sad": ("😢", "Sad", "Reactions"), "pray": ("🙏", "Thank you", "Reactions"), "clap": ("👏", "Applause", "Reactions"), "ok": ("👌", "OK", "Reactions"),
    "party": ("🎉", "Celebrate", "Celebrate"), "fire": ("🔥", "On fire", "Celebrate"), "hundred": ("💯", "Perfect", "Celebrate"), "sparkles": ("✨", "Great", "Celebrate"),
    "cake": ("🎂", "Birthday", "Celebrate"), "rocket": ("🚀", "Launch", "Celebrate"),
    "check": ("✅", "Done", "Work"), "idea": ("💡", "Idea", "Work"), "bug": ("🐛", "Bug", "Work"), "coffee": ("☕", "Coffee break", "Work"),
    "eyes": ("👀", "Looking", "Work"), "think": ("🤔", "Thinking", "Work"), "muscle": ("💪", "Strong", "Work"),
    "cool": ("😎", "Cool", "Fun"), "sleepy": ("😴", "Sleepy", "Fun"), "wave": ("👋", "Hello", "Fun"),
}
REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🙏", "🎉", "👏")


class MessageIn(BaseModel):
    body: str = Field(max_length=4000)
    reply_to_id: int | None = None

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class ConversationIn(BaseModel):
    user_id: int | None = None  # direct message
    name: str | None = Field(None, min_length=1, max_length=120)  # group
    member_ids: list[int] = Field(default_factory=list, max_length=MAX_GROUP)


def _exceptions(ctx: Ctx) -> set[int]:
    return set(ctx.db.scalars(select(CommException.user_id)))


def _deny_message(a: User, b: User) -> str:
    if "founder" in (a.role, b.role) and "employee" in (a.role, b.role):
        return "Employees cannot message the founder directly. Send an escalation to your manager or HR instead."
    if "board_member" in (a.role, b.role):
        return "Board members only communicate with the founder and other board members."
    return "You are not allowed to message this person (people communicate within their branch and reporting line)."


def _require_allowed(ctx: Ctx, others: list[User]) -> None:
    exc = _exceptions(ctx)
    for o in others:
        if not can_message(ctx.user, o, exceptions=exc):
            raise Forbidden(_deny_message(ctx.user, o))
    for a, b in combinations(others, 2):  # nobody in a group may be a pair that the hierarchy forbids
        if not can_message(a, b, exceptions=exc):
            raise Forbidden(f"{a.full_name} and {b.full_name} cannot be in the same chat.")


def _members(ctx: Ctx, conv_id: int) -> list[int]:
    return list(ctx.db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conv_id)))


def _mine(ctx: Ctx, conv_id: int) -> tuple[Conversation, ConversationMember]:
    """Return the conversation only if the caller is a member (404 otherwise: no existence leak)."""
    conv = ctx.db.get(Conversation, conv_id)
    mem = ctx.db.scalar(select(ConversationMember).where(
        ConversationMember.conversation_id == conv_id, ConversationMember.user_id == ctx.user.id))
    if conv is None or mem is None:
        raise NotFound("Conversation not found")
    return conv, mem


def _names(ctx: Ctx, ids) -> dict[int, str]:
    ids = set(ids)
    return {u.id: u.full_name for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _preview(m: Message) -> str:
    """One line for the conversation list."""
    if m.deleted_at is not None:
        return "🚫 Message deleted"
    if m.kind == "image":
        return "📷 Photo"
    if m.kind == "audio":
        return "🎤 Voice message" if (m.file_name or "").startswith("voice-") else f"🎵 {m.file_name}"
    if m.kind == "file":
        return f"📎 {m.file_name}"
    if m.kind == "sticker":
        return f"{STICKERS.get(m.body, ('🙂',))[0]} Sticker"
    return m.body


def _reaction_map(ctx: Ctx, ids: list[int]) -> dict[int, dict[str, list[int]]]:
    out: dict[int, dict[str, list[int]]] = {}
    if ids:
        for r in ctx.db.scalars(select(MessageReaction).where(MessageReaction.message_id.in_(ids)).order_by(MessageReaction.emoji, MessageReaction.user_id)):
            out.setdefault(r.message_id, {}).setdefault(r.emoji, []).append(r.user_id)
    return out


def _reply_map(ctx: Ctx, msgs: list[Message]) -> dict[int, dict]:
    """The quoted message for every reply in `msgs`: who wrote it and a one-line preview (never the file itself)."""
    ids = {m.reply_to_id for m in msgs if m.reply_to_id}
    if not ids:
        return {}
    rows = list(ctx.db.scalars(select(Message).where(Message.id.in_(ids))))
    names = _names(ctx, {r.sender_id for r in rows})
    return {r.id: {"id": r.id, "sender_id": r.sender_id, "sender_name": names.get(r.sender_id, "Former member"), "preview": _preview(r),
                   "kind": "deleted" if r.deleted_at else r.kind} for r in rows}


def _ser_message(m: Message, names: dict[int, str], reactions: dict[str, list[int]] | None = None, reply: dict | None = None) -> dict:
    out = {"id": m.id, "conversation_id": m.conversation_id, "sender_id": m.sender_id,
           "sender_name": names.get(m.sender_id, "Former member"), "body": m.body, "created_at": m.created_at,
           "kind": m.kind or "text", "preview": _preview(m), "edited_at": m.edited_at, "deleted": m.deleted_at is not None,
           "reply_to": reply, "reactions": [{"emoji": e, "user_ids": u} for e, u in (reactions or {}).items()]}
    if m.deleted_at is not None:  # nothing of the content is sent for a deleted message
        out.update(body="", kind="text", reactions=[])
        return out
    if m.kind in ("image", "audio", "file"):
        out["file"] = {"name": m.file_name, "size": m.file_size, "mime": m.mime, "url": f"/chat/messages/{m.id}/file", "duration_s": m.duration_s}
    if m.kind == "sticker":
        out["sticker"] = {"id": m.body, "emoji": STICKERS.get(m.body, ("🙂", ""))[0], "label": STICKERS.get(m.body, ("", "Sticker"))[1]}
    return out


def _ser_conv(ctx: Ctx, conv: Conversation, mem: ConversationMember) -> dict:
    marks = {m.user_id: m for m in ctx.db.scalars(select(ConversationMember).where(ConversationMember.conversation_id == conv.id))}
    ids = list(marks)
    last = ctx.db.scalar(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(1))
    names = _names(ctx, ids + ([last.sender_id] if last else []))
    avatars = dict(ctx.db.execute(select(User.id, User.avatar_name).where(User.id.in_(ids))).all()) if ids else {}
    unread = ctx.db.scalar(select(func.count(Message.id)).where(
        Message.conversation_id == conv.id, Message.id > mem.last_read_message_id, Message.sender_id != ctx.user.id)) or 0
    others = [i for i in ids if i != ctx.user.id]
    can_send = True
    if conv.kind == "dm" and others:
        peer = ctx.db.get(User, others[0])
        can_send = bool(peer and peer.is_active and can_message(ctx.user, peer, exceptions=_exceptions(ctx)))
    title = conv.name if conv.kind == "group" else (names.get(others[0], "Former member") if others else "Just you")
    return {"id": conv.id, "kind": conv.kind, "title": title,
            "members": [{"id": i, "name": names.get(i, ""), "avatar_v": avatars.get(i), "last_read_id": marks[i].last_read_message_id,
                         "last_delivered_id": marks[i].last_delivered_message_id} for i in ids],
            "last_message": _ser_message(last, names) if last else None, "pinned": bool(mem.pinned),
            "unread": unread, "last_message_at": conv.last_message_at, "can_send": can_send}


@router.get("/users")
def directory(q: str | None = None, ctx: Ctx = Depends(get_ctx)):
    """People the caller is allowed to message under the communication hierarchy."""
    stmt = select(User).where(User.is_active.is_(True), User.id != ctx.user.id).order_by(User.full_name)
    if q:
        stmt = stmt.where(User.full_name.ilike(f"%{q.strip()}%"))
    exc = _exceptions(ctx)
    allowed = [u for u in ctx.db.scalars(stmt) if can_message(ctx.user, u, exceptions=exc)][:200]
    return {"items": [{"id": u.id, "full_name": u.full_name, "role": u.role, "designation": u.designation, "avatar_v": u.avatar_name} for u in allowed]}


@router.get("/conversations")
def list_conversations(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(
        select(Conversation, ConversationMember).join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == ctx.user.id)
        .order_by(ConversationMember.pinned.desc(), func.coalesce(Conversation.last_message_at, Conversation.created_at).desc())).all()
    return {"items": [_ser_conv(ctx, c, m) for c, m in rows]}


@router.get("/unread-count")
def unread_count(ctx: Ctx = Depends(get_ctx)):
    n = ctx.db.scalar(
        select(func.count(Message.id)).join(ConversationMember, ConversationMember.conversation_id == Message.conversation_id)
        .where(ConversationMember.user_id == ctx.user.id, Message.id > ConversationMember.last_read_message_id,
               Message.sender_id != ctx.user.id)) or 0
    return {"count": n}


def _active_ids(ctx: Ctx, ids: set[int]) -> set[int]:
    found = set(ctx.db.scalars(select(User.id).where(User.id.in_(ids), User.is_active.is_(True))))
    if found != ids:
        raise AppError("One or more people cannot be added")
    return found


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationIn, ctx: Ctx = Depends(get_ctx)):
    me = ctx.user.id
    if body.user_id is not None:  # direct message: get-or-create
        if body.user_id == me:
            raise AppError("You cannot start a chat with yourself")
        _active_ids(ctx, {body.user_id})
        _require_allowed(ctx, [ctx.db.get(User, body.user_id)])
        key = f"{min(me, body.user_id)}:{max(me, body.user_id)}"
        conv = ctx.db.scalar(select(Conversation).where(Conversation.dm_key == key))
        if conv is None:
            conv = Conversation(kind="dm", dm_key=key, created_by=me)
            ctx.db.add(conv)
            ctx.db.flush()
            ctx.db.add_all([ConversationMember(conversation_id=conv.id, user_id=u) for u in (me, body.user_id)])
            ctx.db.flush()
    else:
        if not body.name:
            raise AppError("A group needs a name")
        ids = _active_ids(ctx, set(body.member_ids) - {me}) if set(body.member_ids) - {me} else set()
        if not ids:
            raise AppError("Add at least one other person")
        _require_allowed(ctx, list(ctx.db.scalars(select(User).where(User.id.in_(ids)))))
        conv = Conversation(kind="group", name=body.name.strip(), created_by=me)
        ctx.db.add(conv)
        ctx.db.flush()
        ctx.db.add_all([ConversationMember(conversation_id=conv.id, user_id=u) for u in ids | {me}])
        ctx.db.flush()
    mem = ctx.db.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conv.id, ConversationMember.user_id == me))
    if mem is None:  # an existing DM the caller is somehow not in cannot happen (key contains their id), but never leak it
        raise NotFound("Conversation not found")
    ctx.db.commit()
    return _ser_conv(ctx, conv, mem)


@router.get("/conversations/{cid}/messages")
def messages(cid: int, before_id: int | None = None, limit: int = 50, q: str | None = Query(None, max_length=100), ctx: Ctx = Depends(get_ctx)):
    """Newest page first (oldest to newest inside the page); pass `before_id` for the page before it. `q` searches this conversation's text."""
    _mine(ctx, cid)
    limit = max(1, min(limit, 100))
    stmt = select(Message).where(Message.conversation_id == cid).order_by(Message.id.desc()).limit(limit)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(Message.deleted_at.is_(None), or_(Message.body.ilike(like, escape="\\"), Message.file_name.ilike(like, escape="\\")))
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = list(ctx.db.scalars(stmt))[::-1]
    names = _names(ctx, {m.sender_id for m in rows})
    react = _reaction_map(ctx, [m.id for m in rows])
    replies = _reply_map(ctx, rows)
    return {"items": [_ser_message(m, names, react.get(m.id), replies.get(m.reply_to_id)) for m in rows], "has_more": len(rows) == limit}


def _checked_conversation(ctx: Ctx, cid: int) -> tuple[Conversation, ConversationMember]:
    """Membership plus the rules that apply to every kind of message."""
    conv, mem = _mine(ctx, cid)
    if conv.kind == "dm":  # a DM with someone who has since left is read-only
        other = next((i for i in _members(ctx, cid) if i != ctx.user.id), None)
        peer = ctx.db.get(User, other) if other is not None else None
        if peer is not None and not peer.is_active:
            raise Forbidden("This person is no longer active")
        if peer is not None:
            _require_allowed(ctx, [peer])  # the hierarchy is re-checked on every send
    return conv, mem


def _valid_reply(ctx: Ctx, cid: int, reply_to_id: int | None) -> int | None:
    if reply_to_id is None:
        return None
    target = ctx.db.get(Message, reply_to_id)
    if target is None or target.conversation_id != cid or target.deleted_at is not None:
        raise AppError("You can only reply to a message in this conversation", status_code=422)
    return target.id


def _post(ctx: Ctx, conv: Conversation, mem: ConversationMember, msg: Message) -> dict:
    ctx.db.add(msg)
    ctx.db.flush()
    conv.last_message_at = msg.created_at or utcnow()
    mem.last_read_message_id = msg.id  # your own message counts as read
    mem.last_delivered_message_id = max(mem.last_delivered_message_id or 0, msg.id)
    out = _ser_message(msg, {ctx.user.id: ctx.user.full_name}, None, _reply_map(ctx, [msg]).get(msg.reply_to_id))
    ctx.db.info.setdefault("push", []).append((_members(ctx, conv.id), {"type": "chat", "data": jsonable_encoder(out)}))
    ctx.db.commit()
    return out


@router.post("/conversations/{cid}/messages", status_code=201)
def send(cid: int, body: MessageIn, ctx: Ctx = Depends(get_ctx)):
    conv, mem = _checked_conversation(ctx, cid)
    return _post(ctx, conv, mem, Message(conversation_id=cid, sender_id=ctx.user.id, body=body.body, reply_to_id=_valid_reply(ctx, cid, body.reply_to_id)))


@router.get("/stickers")
def stickers(ctx: Ctx = Depends(get_ctx)):
    return {"items": [{"id": k, "emoji": e, "label": label, "category": cat} for k, (e, label, cat) in STICKERS.items()], "reactions": list(REACTIONS)}


class StickerIn(BaseModel):
    sticker: str = Field(max_length=40)
    reply_to_id: int | None = None


@router.post("/conversations/{cid}/stickers", status_code=201)
def send_sticker(cid: int, body: StickerIn, ctx: Ctx = Depends(get_ctx)):
    if body.sticker not in STICKERS:
        raise AppError("Unknown sticker", status_code=422)
    conv, mem = _checked_conversation(ctx, cid)
    return _post(ctx, conv, mem, Message(conversation_id=cid, sender_id=ctx.user.id, body=body.sticker, kind="sticker", reply_to_id=_valid_reply(ctx, cid, body.reply_to_id)))


@router.post("/conversations/{cid}/attachments", status_code=201)
async def send_attachment(cid: int, file: UploadFile = File(...), caption: str = Form("", max_length=1000), voice: bool = Form(False),
                          duration: int | None = Form(None, ge=0, le=7200), reply_to_id: int | None = Form(None), ctx: Ctx = Depends(get_ctx)):
    """A photo, document, song or voice recording. Checked like every other upload (allow-list, real content, size)."""
    conv, mem = _checked_conversation(ctx, cid)
    reply_id = _valid_reply(ctx, cid, reply_to_id)
    name, stored, size, ctype, kind = await storage.save_chat_media(ctx.company_id, file, voice=voice)
    if voice and kind == "audio":
        name = f"voice-{utcnow().strftime('%Y%m%d-%H%M%S')}{name[name.rfind('.'):] if '.' in name else ''}"
    try:
        return _post(ctx, conv, mem, Message(conversation_id=cid, sender_id=ctx.user.id, body=caption.strip(), kind=kind, file_name=name,
                                             stored_name=stored, file_size=size, mime=ctype, duration_s=duration if kind == "audio" else None, reply_to_id=reply_id))
    except Exception:
        storage.delete_file(ctx.company_id, stored)  # nothing may be left behind if the message was not saved
        raise


def _message_of_mine(ctx: Ctx, mid: int) -> Message:
    m = ctx.db.get(Message, mid)
    if m is None:
        raise NotFound("Message not found")
    _mine(ctx, m.conversation_id)  # members only; anything else looks like it does not exist
    return m


@router.get("/messages/{mid}/file")
def message_file(mid: int, ctx: Ctx = Depends(get_ctx)):
    m = _message_of_mine(ctx, mid)
    if m.deleted_at is not None or m.kind not in ("image", "audio", "file") or not m.stored_name:
        raise NotFound("This message has no file")
    path = storage.path_for(ctx.company_id, m.stored_name)
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, max-age=3600"}
    if m.kind == "file":  # documents are always downloaded, never rendered
        return FileResponse(path, filename=m.file_name, media_type="application/octet-stream", headers=headers)
    return FileResponse(path, media_type=m.mime, headers=headers, content_disposition_type="inline", filename=m.file_name)


class ReactionIn(BaseModel):
    emoji: str = Field(max_length=16)


@router.post("/messages/{mid}/reactions")
def toggle_reaction(mid: int, body: ReactionIn, ctx: Ctx = Depends(get_ctx)):
    """Adds your reaction, or takes it back if you already reacted with the same emoji."""
    if body.emoji not in REACTIONS:
        raise AppError("Choose one of the available reactions", status_code=422)
    m = _message_of_mine(ctx, mid)
    if m.deleted_at is not None:
        raise NotFound("Message not found")
    existing = ctx.db.get(MessageReaction, (m.id, ctx.user.id, body.emoji))
    if existing is not None:
        ctx.db.delete(existing)
    else:
        ctx.db.add(MessageReaction(message_id=m.id, user_id=ctx.user.id, emoji=body.emoji))
    ctx.db.flush()
    out = _ser_message(m, _names(ctx, {m.sender_id}), _reaction_map(ctx, [m.id]).get(m.id), _reply_map(ctx, [m]).get(m.reply_to_id))
    ctx.db.info.setdefault("push", []).append((_members(ctx, m.conversation_id), {"type": "chat", "data": jsonable_encoder(out)}))
    ctx.db.commit()
    return out


def _republish(ctx: Ctx, m: Message) -> dict:
    out = _ser_message(m, _names(ctx, {m.sender_id}), _reaction_map(ctx, [m.id]).get(m.id), _reply_map(ctx, [m]).get(m.reply_to_id))
    ctx.db.info.setdefault("push", []).append((_members(ctx, m.conversation_id), {"type": "chat", "data": jsonable_encoder(out)}))
    return out


class EditIn(BaseModel):
    body: str = Field(max_length=4000)


@router.patch("/messages/{mid}")
def edit_message(mid: int, body: EditIn, ctx: Ctx = Depends(get_ctx)):
    """Only the sender can change a message, and only its text (or a file's caption). Others see it marked as edited."""
    m = _message_of_mine(ctx, mid)
    if m.sender_id != ctx.user.id or m.deleted_at is not None:
        raise Forbidden("You can only edit your own messages")
    if m.kind == "sticker":
        raise AppError("Stickers cannot be edited")
    text = body.body.strip()
    if not text and m.kind == "text":
        raise AppError("Message cannot be empty", status_code=422)
    _checked_conversation(ctx, m.conversation_id)  # the communication rules still apply
    if text == m.body:  # nothing changed: no "edited" mark and nobody is notified
        return _ser_message(m, _names(ctx, {m.sender_id}), _reaction_map(ctx, [m.id]).get(m.id), _reply_map(ctx, [m]).get(m.reply_to_id))
    m.body, m.edited_at = text, utcnow()
    out = _republish(ctx, m)
    ctx.db.commit()
    return out


@router.delete("/messages/{mid}")
def delete_message(mid: int, ctx: Ctx = Depends(get_ctx)):
    """Deletes your own message for everyone: the text, the file and the reactions go; a "deleted" placeholder remains so replies still make sense."""
    m = _message_of_mine(ctx, mid)
    if m.sender_id != ctx.user.id:
        raise Forbidden("You can only delete your own messages")
    if m.deleted_at is None:
        stored = m.stored_name
        m.deleted_at, m.body, m.stored_name, m.file_name, m.file_size = utcnow(), "", None, None, None
        for r in ctx.db.scalars(select(MessageReaction).where(MessageReaction.message_id == m.id)):
            ctx.db.delete(r)
        ctx.db.flush()
        if stored:
            storage.delete_file(ctx.company_id, stored)
    out = _republish(ctx, m)
    ctx.db.commit()
    return out


class PinIn(BaseModel):
    pinned: bool


@router.put("/conversations/{cid}/pin")
def pin_conversation(cid: int, body: PinIn, ctx: Ctx = Depends(get_ctx)):
    """Pinning is personal: it only changes your own list. At most 5 pinned chats."""
    conv, mem = _mine(ctx, cid)
    if body.pinned and not mem.pinned:
        pinned = ctx.db.scalar(select(func.count(ConversationMember.id)).where(ConversationMember.user_id == ctx.user.id, ConversationMember.pinned.is_(True))) or 0
        if pinned >= 5:
            raise AppError("You can pin up to 5 chats. Unpin one first.")
    mem.pinned = body.pinned
    ctx.db.commit()
    return _ser_conv(ctx, conv, mem)


@router.get("/presence")
def presence(ctx: Ctx = Depends(get_ctx)):
    """Who among the people you chat with is online right now, and when the others were last seen."""
    mine = select(ConversationMember.conversation_id).where(ConversationMember.user_id == ctx.user.id)
    partners = set(ctx.db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id.in_(mine), ConversationMember.user_id != ctx.user.id)))
    users = list(ctx.db.scalars(select(User).where(User.id.in_(partners), User.is_active.is_(True)))) if partners else []
    return {"items": [{"user_id": u.id, "online": manager.is_online(ctx.company_id, u.id), "last_seen_at": u.last_seen_at} for u in users]}


@router.post("/conversations/{cid}/read", status_code=204)
def mark_read(cid: int, ctx: Ctx = Depends(get_ctx)):
    _, mem = _mine(ctx, cid)
    last = ctx.db.scalar(select(func.max(Message.id)).where(Message.conversation_id == cid)) or 0
    changed = last > mem.last_read_message_id
    mem.last_read_message_id = max(mem.last_read_message_id, last)
    mem.last_delivered_message_id = max(mem.last_delivered_message_id or 0, last)
    if changed:
        ctx.db.info.setdefault("push", []).append(([i for i in _members(ctx, cid) if i != ctx.user.id],
                                                   {"type": "chat_read", "data": {"conversation_id": cid, "user_id": ctx.user.id, "last_read_id": mem.last_read_message_id}}))
    ctx.db.commit()


# ---- founder-managed exceptions to "employees cannot message the founder" ------------------------------------

founder_only = require_roles("founder")


@router.get("/exceptions")
def list_exceptions(ctx: Ctx = Depends(founder_only)):
    rows = ctx.db.scalars(select(User).join(CommException, CommException.user_id == User.id).order_by(User.full_name))
    return {"items": [{"id": u.id, "full_name": u.full_name, "designation": u.designation, "avatar_v": u.avatar_name} for u in rows]}


@router.put("/exceptions/{user_id}", status_code=204)
def add_exception(user_id: int, ctx: Ctx = Depends(founder_only)):
    u = ctx.db.get(User, user_id)
    if u is None or not u.is_active or u.role != "employee":
        raise AppError("Only active employees can be given direct access to the founder")
    if ctx.db.get(CommException, user_id) is None:
        ctx.db.add(CommException(user_id=user_id, created_by=ctx.user.id))
        notify(ctx.db, [user_id], "Direct line to the founder", "You can now message the founder directly.", "org")
        audit(ctx, "chat.exception_added", "user", user_id)
    ctx.db.commit()


@router.delete("/exceptions/{user_id}", status_code=204)
def remove_exception(user_id: int, ctx: Ctx = Depends(founder_only)):
    row = ctx.db.get(CommException, user_id)
    if row is None:
        raise NotFound("No exception for this person")
    ctx.db.delete(row)
    audit(ctx, "chat.exception_removed", "user", user_id)
    ctx.db.commit()
