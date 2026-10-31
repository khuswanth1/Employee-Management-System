"""Webhook outbox + delivery.

emit() writes delivery rows in the caller's transaction (transactional outbox). A background worker
(and process_due() in tests) delivers them with HMAC-SHA256 signatures and exponential backoff.
"""
import ipaddress
import json
import logging
import socket
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt, sign_payload
from app.db.base import utcnow
from app.db.tenant_models import Webhook, WebhookDelivery

log = logging.getLogger("worksphere.webhooks")

EVENTS = [
    "employee.created", "employee.offboarded",
    "project.created", "team.created", "team.project_assigned", "task.created", "task.updated", "task.approved",
    "daily_update.submitted", "leave.requested", "leave.decided",
    "attendance.checked_in", "attendance.checked_out", "webhook.test",
]


def validate_target_url(url: str) -> None:
    """SSRF guard: https only (http allowed in dev) and no private/loopback targets by default."""
    p = urlparse(url)
    s = get_settings()
    allow_private = s.webhook_allow_private_urls
    if p.scheme not in ("https", "http") or not p.hostname:
        raise AppError("Webhook URL must be an http(s) URL")
    if p.scheme == "http" and not allow_private:
        raise AppError("Webhook URL must use https")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise AppError("Webhook host cannot be resolved")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise AppError("Webhook URL resolves to a non-public address")


def emit(db: Session, event: str, payload: dict) -> None:
    hooks = db.scalars(select(Webhook).where(Webhook.is_active.is_(True))).all()
    for h in hooks:
        if event in (h.events or []):
            db.add(WebhookDelivery(webhook_id=h.id, event=event, payload=payload))


def _attempt(db: Session, d: WebhookDelivery, client: httpx.Client) -> None:
    hook = db.get(Webhook, d.webhook_id)
    s = get_settings()
    now = utcnow()
    body = json.dumps({"id": d.id, "event": d.event, "created_at": d.created_at.isoformat(), "data": d.payload}).encode()
    ts = str(int(now.timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "WorkSphere-Webhooks/1.0",
        "X-WorkSphere-Event": d.event,
        "X-WorkSphere-Delivery": str(d.id),
        "X-WorkSphere-Timestamp": ts,
        "X-WorkSphere-Signature": sign_payload(decrypt(hook.secret_encrypted), ts, body),
    }
    d.attempts += 1
    try:
        if not s.webhook_allow_private_urls:
            validate_target_url(hook.url)
        # No redirects: a redirect could bounce a validated URL to an internal one.
        r = client.post(hook.url, content=body, headers=headers, timeout=10, follow_redirects=False)
        d.last_status_code = r.status_code
        ok = 200 <= r.status_code < 300
        d.last_error = None if ok else f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001 - delivery errors are recorded, not raised
        ok = False
        d.last_status_code = None
        d.last_error = str(e)[:500]
    if ok:
        d.status, d.delivered_at, d.next_attempt_at = "success", now, None
    elif d.attempts >= s.webhook_max_attempts:
        d.status, d.next_attempt_at = "failed", None
    else:
        d.next_attempt_at = now + timedelta(seconds=30 * 2 ** (d.attempts - 1))


def process_due(db: Session, client: httpx.Client | None = None, limit: int = 50) -> int:
    own = client is None
    client = client or httpx.Client()
    try:
        due = db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= utcnow())
            .order_by(WebhookDelivery.id)
            .limit(limit)
        ).all()
        for d in due:
            _attempt(db, d, client)
            db.commit()
        return len(due)
    finally:
        if own:
            client.close()


def retry_now(d: WebhookDelivery) -> None:
    d.status, d.attempts, d.next_attempt_at = "pending", 0, utcnow()
