import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.core.config import get_settings

ALGO = "HS256"
ISSUER = "worksphere"


def _prehash(password: str) -> bytes:
    # bcrypt truncates at 72 bytes; prehash so long passphrases keep full entropy.
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode())
    except ValueError:
        return False


# Dummy hash so unknown users cost the same as wrong passwords (no user enumeration by timing).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise ValueError("Password must mix upper/lower case letters and digits")


def validate_temporary_password(password: str) -> None:
    """Passwords an admin sets for an employee (new account or reset): 4 to 12 characters. The employee can then choose
    their own password, which must meet validate_password_strength."""
    if not 4 <= len(password) <= 12:
        raise ValueError("Password must be 4 to 12 characters")


def create_token(*, sub: int, role: str, tenant_id: int | None, typ: str = "access", dev: str | None = None, sv: int = 0) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    ttl = {"access": timedelta(minutes=s.access_token_minutes), "mfa": timedelta(minutes=5)}.get(typ, timedelta(days=s.refresh_token_days))
    payload = {
        "iss": ISSUER,
        "sub": str(sub),
        "role": role,
        "tid": tenant_id,
        "typ": typ,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
        "sv": sv,  # session version: bumping the user's value revokes every token issued before
    }
    if dev:
        payload["dev"] = dev  # binds the token to one browser, see app/core/session.py
    return jwt.encode(payload, s.secret_key, algorithm=ALGO)


def decode_token(token: str, expected_typ: str = "access") -> dict:
    payload = jwt.decode(
        token,
        get_settings().secret_key,
        algorithms=[ALGO],
        issuer=ISSUER,
        options={"require": ["exp", "sub", "iss", "typ"]},
    )
    if payload.get("typ") != expected_typ:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()
