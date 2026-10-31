"""TOTP (RFC 6238, SHA-1, 6 digits, 30 s) and one-time recovery codes. Standard library only."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept the previous and next step to tolerate clock drift
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(value).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify_totp(secret: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """Return the matched time step, or None. A step at or before `last_step` is refused so a code cannot be replayed."""
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    for step in range(base - WINDOW, base + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "WorkSphere") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"


def _norm(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_recovery(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(plain codes shown once, hashes to store)"""
    plain = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(RECOVERY_CODES)]
    return plain, [hash_recovery(c) for c in plain]


def consume_recovery(stored: list[str] | None, code: str) -> list[str] | None:
    """Return the remaining hashes if `code` was valid (and is now spent), else None."""
    h = hash_recovery(code)
    for s in stored or []:
        if hmac.compare_digest(s, h):
            return [x for x in stored if x != s]
    return None
