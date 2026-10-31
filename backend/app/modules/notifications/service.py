import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.tenant_models import Notification, User

log = logging.getLogger("worksphere.notify")


def notify(db: Session, user_ids: list[int], title: str, body: str | None = None, kind: str = "info", link: str | None = None) -> None:
    """Persist notifications in the caller's transaction; the WebSocket push happens after the
    request succeeds (see deps.get_ctx), so a rolled-back request never pushes."""
    ids = sorted({u for u in user_ids if u})
    if not ids:
        return
    rows = [Notification(user_id=u, title=title, body=body, kind=kind, link=link) for u in ids]
    db.add_all(rows)
    db.flush()
    for n in rows:
        db.info.setdefault("push", []).append(
            ([n.user_id], {"type": "notification", "data": {"id": n.id, "title": title, "body": body, "kind": kind, "link": link}})
        )
    _email(db, ids, title, body)


def live_event(db: Session, user_ids: list[int], event: str, data: dict) -> None:
    """Push a non-persisted live-update hint (e.g. 'task.updated') after commit."""
    db.info.setdefault("push", []).append((sorted(set(user_ids)), {"type": "event", "event": event, "data": data}))


def _email(db: Session, user_ids: list[int], title: str, body: str | None) -> None:
    s = get_settings()
    if not s.smtp_host:
        return
    emails = db.scalars(select(User.email).where(User.id.in_(user_ids))).all()
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            for addr in emails:
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = s.smtp_from, addr, title
                msg.set_content(body or title)
                smtp.send_message(msg)
    except Exception:
        log.exception("email notification failed")  # email is optional; never fail the request
