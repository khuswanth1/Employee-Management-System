from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import PlatformBase, utcnow


class PlatformUser(PlatformBase):
    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # bump to sign out every session
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(255))
    mfa_last_step: Mapped[int | None] = mapped_column(Integer)
    mfa_recovery: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevokedToken(PlatformBase):
    """Server-side denylist of token ids (jti) signed out before they expire. Rows are pruned after `expires_at`."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Company(PlatformBase):
    """Tenant registration. db_url_encrypted is a Fernet token; it never leaves the server."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | suspended
    db_name: Mapped[str] = mapped_column(String(100), unique=True)
    db_url_encrypted: Mapped[str] = mapped_column(Text)
    max_users: Mapped[int] = mapped_column(Integer, default=500)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
