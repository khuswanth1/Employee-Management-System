"""Request context & authorization.

Tenant resolution: the tenant is taken ONLY from the signed JWT's `tid`, re-validated against the
platform registry on every request. No header, query or body field can select a tenant.
"""
import logging
from collections.abc import Callable, Generator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.core.session import ACCESS_COOKIE, DEVICE_COOKIE, check_binding, check_not_revoked, check_session_version, require_csrf_header
from app.db.platform_models import Company, PlatformUser
from app.db.session import platform_session
from app.db.tenant_models import User
from app.realtime import publish_threadsafe
from app.tenancy.manager import tenants

log = logging.getLogger("worksphere.auth")
bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    user: User
    db: Session
    company_id: int
    company_slug: str
    ip: str | None

    @property
    def role(self) -> str:
        return self.user.role


def request_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str:
    """Bearer header (API clients) or the browser's session cookie. Cookie-authenticated writes need the CSRF header."""
    if creds is not None:
        return creds.credentials
    cookie = request.cookies.get(ACCESS_COOKIE)
    if not cookie:
        raise Unauthorized()
    require_csrf_header(request)
    return cookie


def resolve_tenant_user(token: str, device: str | None = None, expected_typ: str = "access") -> tuple[Company, Session, User]:
    """Validate a token and open the tenant DB session. Caller must close the session."""
    try:
        claims = decode_token(token, expected_typ=expected_typ)
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token")
    check_binding(claims, device)
    check_not_revoked(claims)
    tid = claims.get("tid")
    if tid is None or claims.get("role") == "platform_admin":
        raise Unauthorized("Invalid token for tenant access")
    with platform_session() as pdb:
        company = pdb.get(Company, int(tid))
        if company is None:
            raise Unauthorized("Unknown tenant")
        if company.status != "active":
            raise Forbidden("This company account is suspended")
        pdb.expunge(company)
    db = tenants.session_for(company)
    try:
        user = db.get(User, int(claims["sub"]))
        if user is None or not user.is_active or user.status == "offboarded":
            raise Unauthorized("Account is disabled")
        check_session_version(claims, user.session_version)  # password change / reset / "sign out everywhere"
        # Role comes from the DB, not the token, so demotions take effect immediately.
        return company, db, user
    except Exception:
        db.close()
        raise


def get_ctx(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Generator[Ctx, None, None]:
    token = request_token(request, creds)
    company, db, user = resolve_tenant_user(token, request.cookies.get(DEVICE_COOKIE))
    db.info["company_id"] = company.id
    ctx = Ctx(user=user, db=db, company_id=company.id, company_slug=company.slug, ip=request.client.host if request.client else None)
    try:
        yield ctx
    except Exception:
        db.rollback()
        db.info.pop("push", None)
        raise
    else:
        for user_ids, message in db.info.pop("push", []):
            publish_threadsafe(company.id, user_ids, message)
    finally:
        db.close()


def require_roles(*roles: str) -> Callable[..., Ctx]:
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ctx.role not in roles:
            raise Forbidden()
        return ctx

    return dep


def get_platform_admin(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Generator[tuple[PlatformUser, Session], None, None]:
    token = request_token(request, creds)
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token")
    check_binding(claims, request.cookies.get(DEVICE_COOKIE))
    check_not_revoked(claims)
    if claims.get("role") != "platform_admin" or claims.get("tid") is not None:
        raise Forbidden("Platform administrator access required")
    db = platform_session()
    try:
        admin = db.get(PlatformUser, int(claims["sub"]))
        if admin is None or not admin.is_active:
            raise Unauthorized("Account is disabled")
        check_session_version(claims, admin.session_version)
        yield admin, db
    finally:
        db.close()
