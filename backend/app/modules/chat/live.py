"""Chat's live signals over the existing /ws socket: presence, last seen, typing and delivery acknowledgements.

Every function is synchronous and opens its own short tenant session, so the socket handler can run them in the thread pool.
Events only ever name people who share a conversation with the sender, so nothing here reaches anybody outside it.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.tenant_models import ConversationMember, Message, User
from app.tenancy.manager import tenants


def _now() -> datetime:
    return datetime.now(timezone.utc)


def partners_of(company, user_id: int) -> list[int]:
    """People the user shares at least one conversation with."""
    with tenants.session_for(company) as db:
        mine = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user_id)
        return sorted(set(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id.in_(mine), ConversationMember.user_id != user_id))))


def stamp_last_seen(company, user_id: int) -> str:
    """Remember when this person was last connected; returns the timestamp for the presence event."""
    with tenants.session_for(company) as db:
        u = db.get(User, user_id)
        now = _now()
        if u is not None:
            u.last_seen_at = now
            db.commit()
        return now.isoformat()


def typing_audience(company, user_id: int, conversation_id: int) -> list[int] | None:
    """The other members of a conversation the user belongs to, or None when they are not a member (the signal is dropped)."""
    with tenants.session_for(company) as db:
        members = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation_id)))
        if user_id not in members:
            return None
        return [m for m in members if m != user_id]


def acknowledge(company, user_id: int, conversation_id: int, message_id: int) -> tuple[list[int], int] | None:
    """The user's client received messages up to `message_id`. Returns (people to tell, the new delivered mark) or None when nothing changed."""
    with tenants.session_for(company) as db:
        mem = db.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id))
        if mem is None:
            return None
        newest = db.scalar(select(func.max(Message.id)).where(Message.conversation_id == conversation_id)) or 0
        mark = min(message_id, newest)  # a client cannot claim to have received something that does not exist yet
        if mark <= (mem.last_delivered_message_id or 0):
            return None
        mem.last_delivered_message_id = mark
        db.commit()
        others = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id != user_id)))
        return others, mark
