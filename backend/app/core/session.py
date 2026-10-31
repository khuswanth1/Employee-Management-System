"""Browser sessions: httpOnly cookies bound to the browser that signed in.

The SPA never sees its tokens. Login (with the `X-WS-Client: web` header) sets three httpOnly, SameSite=Strict cookies:
`ws_access`, `ws_refresh` and `ws_device` (a random id minted once per browser). Every token issued to the browser carries
`dev` = hash(ws_device), so a token copied to another browser or a script is rejected there: it lacks the matching device
cookie. State-changing requests that rely on cookies must also send `X-WS-Client` (a header a cross-site page cannot add
without CORS permission), which is the CSRF check. API clients (curl, scripts, tests) keep using bearer tokens.
"""
import hashlib
import secrets

from fastapi import Request, Response

from app.core.config import get_settings
from app.core.errors import Forbidden, Unauthorized

ACCESS_COOKIE = "ws_access"
REFRESH_COOKIE = "ws_refresh"
DEVICE_COOKIE = "ws_device"
MARKER_COOKIE = "ws_session"  # readable by the SPA, holds nothing secret: only says "a session cookie exists"
CLIENT_HEADER = "x-ws-client"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def device_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def is_web_client(request: Request) -> bool:
    return request.headers.get(CLIENT_HEADER, "").lower() == "web"


def require_csrf_header(request: Request) -> None:
    if request.method not in SAFE_METHODS and not is_web_client(request):
        raise Forbidden("Missing X-WS-Client header")


def check_binding(claims: dict, device_raw: str | None) -> None:
    """A token minted for a browser only works together with that browser's device cookie."""
    dev = claims.get("dev")
    if dev and (not device_raw or not secrets.compare_digest(device_hash(device_raw), str(dev))):
        raise Unauthorized("Invalid or expired token")


def check_not_revoked(claims: dict) -> None:
    """Reject a token that was signed out (its jti is on the platform-wide denylist)."""
    from app.db.platform_models import RevokedToken
    from app.db.session import platform_session

    jti = claims.get("jti")
    if not jti:
        return
    with platform_session() as pdb:
        if pdb.get(RevokedToken, str(jti)) is not None:
            raise Unauthorized("Invalid or expired token")


def check_session_version(claims: dict, current: int) -> None:
    if int(claims.get("sv", 0)) != int(current or 0):
        raise Unauthorized("Session expired, please sign in again")


def revoke_tokens(tokens: list[str | None], expected: tuple[str, ...] = ("access", "refresh")) -> None:
    """Add the ids of still-valid tokens to the denylist (signature checked; garbage and expired tokens are ignored)."""
    import jwt
    from datetime import datetime, timezone

    from app.core.security import decode_token
    from app.db.platform_models import RevokedToken
    from app.db.session import platform_session

    now = datetime.now(timezone.utc)
    rows: dict[str, datetime] = {}
    for raw, typ in zip(tokens, expected):
        if not raw:
            continue
        try:
            claims = decode_token(raw, expected_typ=typ)
        except jwt.PyJWTError:
            continue
        if claims.get("jti"):
            rows[str(claims["jti"])] = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    with platform_session() as pdb:
        pdb.query(RevokedToken).filter(RevokedToken.expires_at < now).delete(synchronize_session=False)  # keep the table small
        for jti, exp in rows.items():
            if pdb.get(RevokedToken, jti) is None:
                pdb.add(RevokedToken(jti=jti, expires_at=exp))
        pdb.commit()


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def new_device_id() -> str:
    return secrets.token_urlsafe(32)


def set_session(response: Response, request: Request, access: str, refresh: str, device_raw: str) -> None:
    s = get_settings()
    kw = dict(httponly=True, samesite="strict", secure=_secure(request), path="/")
    response.set_cookie(ACCESS_COOKIE, access, max_age=s.access_token_minutes * 60, **kw)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=s.refresh_token_days * 86400, **kw)
    response.set_cookie(DEVICE_COOKIE, device_raw, max_age=400 * 86400, **kw)
    response.set_cookie(MARKER_COOKIE, "1", max_age=s.refresh_token_days * 86400, httponly=False, samesite="strict", secure=_secure(request), path="/")


def clear_session(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/", httponly=True, samesite="strict")
    response.delete_cookie(MARKER_COOKIE, path="/", samesite="strict")  # the device cookie stays: it identifies the browser
