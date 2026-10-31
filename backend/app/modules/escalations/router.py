"""Structured upward communication: employee -> manager / HR -> founder.

Employees cannot message the founder directly (see access.can_message). Instead they open an escalation with their
branch manager or HR. The handler resolves it, or escalates it to the founder with a note. Every step notifies the
people involved and is written to the audit log.
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.access import same_branch, user_scope
from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import Escalation, User
from app.deps import Ctx, get_ctx
from app.modules.notifications.service import notify

router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=4000)
    route: Literal["manager", "hr"] = "manager"

    @field_validator("subject", "body")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Too short")
        return v


class EscalateIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=4000)


def _names(ctx: Ctx, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {u.id: u.full_name for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def ser(ctx: Ctx, e: Escalation, names: dict[int, str] | None = None) -> dict:
    names = names or _names(ctx, [e.created_by, e.assignee_id, e.escalated_by, e.resolved_by])
    return {"id": e.id, "subject": e.subject, "body": e.body, "level": e.level, "status": e.status,
            "created_by": e.created_by, "created_by_name": names.get(e.created_by), "assignee_id": e.assignee_id,
            "assignee_name": names.get(e.assignee_id), "escalated_by_name": names.get(e.escalated_by), "escalation_note": e.escalation_note,
            "resolution": e.resolution, "resolved_by_name": names.get(e.resolved_by), "created_at": e.created_at,
            "updated_at": e.updated_at, "can_act": _can_act(ctx, e)}


def _hr_in_scope(ctx: Ctx, creator: User) -> list[int]:
    hrs = ctx.db.scalars(select(User).where(User.role == "hr", User.is_active.is_(True)))
    return [h.id for h in hrs if same_branch(h, creator)]


def _can_act(ctx: Ctx, e: Escalation) -> bool:
    """May the caller escalate/resolve this one right now?"""
    if e.status == "resolved":
        return False
    if e.level == "founder":
        return ctx.role == "founder"
    if e.level == "manager":
        return ctx.role == "manager" and e.assignee_id == ctx.user.id
    creator = ctx.db.get(User, e.created_by)
    return ctx.role == "hr" and creator is not None and same_branch(ctx.user, creator)


def _visible(ctx: Ctx, e: Escalation) -> bool:
    me = ctx.user.id
    if ctx.role == "founder" or me in (e.created_by, e.escalated_by, e.resolved_by):
        return True
    if ctx.role == "manager":
        return e.assignee_id == me
    if ctx.role == "hr":  # branch HR never sees another branch's escalations
        creator = ctx.db.get(User, e.created_by)
        return e.level == "hr" and creator is not None and same_branch(ctx.user, creator)
    return False


def _get(ctx: Ctx, eid: int) -> Escalation:
    e = ctx.db.get(Escalation, eid)
    if e is None or not _visible(ctx, e):
        raise NotFound("Escalation not found")
    return e


@router.post("", status_code=201)
def create(body: EscalationIn, ctx: Ctx = Depends(get_ctx)):
    me = ctx.user
    if me.role not in ("employee", "manager"):
        raise Forbidden("Only employees and managers open escalations; founders and HR can message each other directly.")
    if me.role == "manager" and body.route == "manager":
        raise AppError("Managers escalate to HR")
    assignee, notify_ids = None, []
    if body.route == "manager":
        boss = ctx.db.get(User, me.manager_id) if me.manager_id else None
        if boss is None or not boss.is_active or boss.role != "manager":
            raise AppError("You have no active line manager. Route this to HR instead.")
        assignee, notify_ids = boss.id, [boss.id]
    else:
        notify_ids = _hr_in_scope(ctx, me)
        if not notify_ids:
            raise AppError("There is no HR contact for your branch yet. Please contact your administrator.")
    e = Escalation(created_by=me.id, subject=body.subject, body=body.body, level=body.route, assignee_id=assignee, status="open")
    ctx.db.add(e)
    ctx.db.flush()
    notify(ctx.db, notify_ids, "New escalation", f"{me.full_name}: {e.subject}", "escalation", "/escalations")
    audit(ctx, "escalation.created", "escalation", e.id, {"route": body.route})
    ctx.db.commit()
    return ser(ctx, e)


@router.get("")
def list_escalations(box: Literal["mine", "inbox"] = "mine", status: str | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Escalation).order_by(Escalation.updated_at.desc(), Escalation.id.desc())
    if box == "mine":
        stmt = stmt.where(Escalation.created_by == ctx.user.id)
    elif ctx.role == "manager":
        stmt = stmt.where(or_(Escalation.assignee_id == ctx.user.id, Escalation.escalated_by == ctx.user.id))
    elif ctx.role == "hr":
        stmt = stmt.join(User, User.id == Escalation.created_by).where(
            or_(Escalation.level == "hr", Escalation.escalated_by == ctx.user.id), user_scope(ctx))
    elif ctx.role == "founder":
        stmt = stmt.where(Escalation.level == "founder")
    else:
        raise Forbidden()
    if status:
        stmt = stmt.where(Escalation.status == status)
    people = _names(ctx, ctx.db.scalars(select(User.id)))
    return paginate(ctx.db, stmt, params, lambda e: ser(ctx, e, people))


@router.get("/{eid}")
def detail(eid: int, ctx: Ctx = Depends(get_ctx)):
    return ser(ctx, _get(ctx, eid))


@router.post("/{eid}/escalate")
def escalate(eid: int, body: EscalateIn, ctx: Ctx = Depends(get_ctx)):
    e = _get(ctx, eid)
    if not _can_act(ctx, e) or e.level == "founder":
        raise Forbidden("Only the current handler (manager or HR) can escalate this to the founder")
    if e.status == "resolved":
        raise Conflict("Already resolved")
    e.level, e.status, e.escalated_by, e.escalation_note, e.assignee_id, e.updated_at = "founder", "escalated", ctx.user.id, body.note.strip(), None, utcnow()
    founders = list(ctx.db.scalars(select(User.id).where(User.role == "founder", User.is_active.is_(True))))
    notify(ctx.db, founders, "Escalation needs you", f"{ctx.user.full_name} escalated: {e.subject}", "escalation", "/escalations")
    notify(ctx.db, [e.created_by], "Your escalation moved up", f"'{e.subject}' was escalated to the founder.", "escalation", "/escalations")
    audit(ctx, "escalation.escalated", "escalation", e.id)
    ctx.db.commit()
    return ser(ctx, e)


@router.post("/{eid}/resolve")
def resolve(eid: int, body: ResolveIn, ctx: Ctx = Depends(get_ctx)):
    e = _get(ctx, eid)
    if not _can_act(ctx, e):
        raise Forbidden("You cannot resolve this escalation")
    e.status, e.resolution, e.resolved_by, e.updated_at = "resolved", body.resolution.strip(), ctx.user.id, utcnow()
    notify(ctx.db, [e.created_by] + ([e.escalated_by] if e.escalated_by and e.escalated_by != ctx.user.id else []),
           "Escalation resolved", f"'{e.subject}': {e.resolution[:120]}", "escalation", "/escalations")
    audit(ctx, "escalation.resolved", "escalation", e.id)
    ctx.db.commit()
    return ser(ctx, e)
