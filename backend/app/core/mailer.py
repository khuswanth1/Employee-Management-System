"""Transactional e-mail (password reset, verification). Callers use `mailer.send_email(...)` so tests can replace it.

Never log message bodies: they contain single-use links."""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("worksphere.mail")


def send_email(to: str, subject: str, body: str) -> bool:
    """Returns True if the message was handed to the SMTP server. Never raises."""
    s = get_settings()
    if not s.smtp_host:
        log.warning("SMTP is not configured; an e-mail (%s) was not sent", subject)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("sending e-mail failed (%s)", subject)
        return False
