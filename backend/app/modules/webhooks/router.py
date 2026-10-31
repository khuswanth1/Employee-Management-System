import secrets

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.common import PageParams, audit, paginate
from app.core.errors import AppError, NotFound
from app.core.security import encrypt
from app.db.base import utcnow
from app.db.tenant_models import Webhook, WebhookDelivery
from app.deps import Ctx, require_roles
from app.modules.webhooks.service import EVENTS, _attempt, retry_now, validate_target_url

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
founder = require_roles("founder")


class WebhookIn(BaseModel):
    url: str = Field(max_length=500)
    events: list[str] = Field(min_length=1)
    is_active: bool = True

    @field_validator("events")
    @classmethod
    def _ev(cls, v: list[str]) -> list[str]:
        bad = [e for e in v if e not in EVENTS or e == "webhook.test"]
        if bad:
            raise ValueError(f"Unknown events: {bad}")
        return sorted(set(v))


def ser(h: Webhook, secret: str | None = None) -> dict:
    d = {"id": h.id, "url": h.url, "events": h.events, "is_active": h.is_active, "created_at": h.created_at}
    if secret:
        d["secret"] = secret  # shown exactly once
    return d


def ser_delivery(d: WebhookDelivery) -> dict:
    return {"id": d.id, "webhook_id": d.webhook_id, "event": d.event, "status": d.status, "attempts": d.attempts,
            "last_status_code": d.last_status_code, "last_error": d.last_error, "next_attempt_at": d.next_attempt_at,
            "created_at": d.created_at, "delivered_at": d.delivered_at}


def _get(ctx: Ctx, wid: int) -> Webhook:
    h = ctx.db.get(Webhook, wid)
    if h is None:
        raise NotFound()
    return h


@router.get("/events")
def events(ctx: Ctx = Depends(founder)):
    return {"items": [e for e in EVENTS if e != "webhook.test"]}


@router.get("")
def list_hooks(ctx: Ctx = Depends(founder)):
    return {"items": [ser(h) for h in ctx.db.scalars(select(Webhook).order_by(Webhook.id))]}


@router.post("", status_code=201)
def create(body: WebhookIn, ctx: Ctx = Depends(founder)):
    validate_target_url(body.url)
    secret = "whsec_" + secrets.token_urlsafe(32)
    h = Webhook(url=body.url, events=body.events, is_active=body.is_active, secret_encrypted=encrypt(secret), created_by=ctx.user.id)
    ctx.db.add(h)
    ctx.db.flush()
    audit(ctx, "webhook.created", "webhook", h.id, {"url": h.url})
    ctx.db.commit()
    return ser(h, secret)


@router.patch("/{wid}")
def update(wid: int, body: WebhookIn, ctx: Ctx = Depends(founder)):
    h = _get(ctx, wid)
    validate_target_url(body.url)
    h.url, h.events, h.is_active = body.url, body.events, body.is_active
    audit(ctx, "webhook.updated", "webhook", h.id)
    ctx.db.commit()
    return ser(h)


@router.post("/{wid}/rotate-secret")
def rotate(wid: int, ctx: Ctx = Depends(founder)):
    h = _get(ctx, wid)
    secret = "whsec_" + secrets.token_urlsafe(32)
    h.secret_encrypted = encrypt(secret)
    audit(ctx, "webhook.secret_rotated", "webhook", h.id)
    ctx.db.commit()
    return ser(h, secret)


@router.delete("/{wid}", status_code=204)
def delete(wid: int, ctx: Ctx = Depends(founder)):
    h = _get(ctx, wid)
    ctx.db.query(WebhookDelivery).filter(WebhookDelivery.webhook_id == h.id).delete()
    ctx.db.delete(h)
    audit(ctx, "webhook.deleted", "webhook", wid)
    ctx.db.commit()


@router.post("/{wid}/test")
def test(wid: int, ctx: Ctx = Depends(founder)):
    """Send a signed test event synchronously and return the outcome."""
    h = _get(ctx, wid)
    d = WebhookDelivery(webhook_id=h.id, event="webhook.test", payload={"message": "Hello from WorkSphere"}, next_attempt_at=None)
    ctx.db.add(d)
    ctx.db.flush()
    d.created_at = utcnow()
    with httpx.Client() as client:
        _attempt(ctx.db, d, client)
    if d.status == "pending":
        d.status = "failed"  # tests are never retried
        d.next_attempt_at = None
    ctx.db.commit()
    return ser_delivery(d)


@router.get("/deliveries/log")
def deliveries(webhook_id: int | None = None, status: str | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(founder)):
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.id.desc())
    if webhook_id:
        stmt = stmt.where(WebhookDelivery.webhook_id == webhook_id)
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    return paginate(ctx.db, stmt, params, ser_delivery)


@router.post("/deliveries/{did}/retry")
def retry(did: int, ctx: Ctx = Depends(founder)):
    d = ctx.db.get(WebhookDelivery, did)
    if d is None:
        raise NotFound()
    if d.status == "success":
        raise AppError("Delivery already succeeded")
    retry_now(d)
    ctx.db.commit()
    return ser_delivery(d)
