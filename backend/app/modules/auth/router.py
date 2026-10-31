import logging

import jwt
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select

from app.access import MANAGER_PERMISSIONS, has_permission
from app.common import audit
from app.core.errors import AppError, Forbidden, Unauthorized
from app.core.ratelimit import login_limiter
from app.core.security import burn_password_check, create_token, decode_token, hash_password, verify_password
from app.db.platform_models import Company, PlatformUser
from app.db.session import platform_session
from app.db.tenant_models import User
from app.core.session import (ACCESS_COOKIE, DEVICE_COOKIE, REFRESH_COOKIE, check_binding, check_not_revoked, check_session_version, clear_session,
                              device_hash, is_web_client, new_device_id, require_csrf_header, revoke_tokens, set_session)
from app.deps import Ctx, bearer as bearer_scheme, get_ctx, get_platform_admin, request_token, resolve_tenant_user
from app.modules.auth.schemas import ChangePasswordIn, LoginIn, PlatformLoginIn, ProfileUpdate, RefreshIn, TokenOut
from app.tenancy.manager import tenants


log = logging.getLogger("worksphere.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

BAD_CREDS = "Invalid credentials"


def _tokens(sub: int, role: str, tid: int | None, request: Request, response: Response, sv: int = 0) -> TokenOut:
    """Browsers (X-WS-Client: web) get httpOnly cookies bound to their device id; API clients get bearer tokens."""
    if not is_web_client(request):
        return TokenOut(
            access_token=create_token(sub=sub, role=role, tenant_id=tid, sv=sv),
            refresh_token=create_token(sub=sub, role=role, tenant_id=tid, typ="refresh", sv=sv),
            role=role,
        )
    device = request.cookies.get(DEVICE_COOKIE) or new_device_id()
    dev = device_hash(device)
    set_session(
        response, request,
        create_token(sub=sub, role=role, tenant_id=tid, dev=dev, sv=sv),
        create_token(sub=sub, role=role, tenant_id=tid, typ="refresh", dev=dev, sv=sv),
        device,
    )
    return TokenOut(role=role, token_type="cookie")


def _mfa_step(sub: int, role: str, tid: int | None, sv: int) -> TokenOut:
    """Password accepted but a second factor is needed: a short-lived single-purpose token, no session yet."""
    return TokenOut(mfa_required=True, mfa_token=create_token(sub=sub, role=role, tenant_id=tid, typ="mfa", sv=sv))


def _tenant_match(company: Company, email: str, password: str) -> User | None:
    """Return the user (detached) if email+password are valid in this company, else None."""
    with tenants.session_for(company) as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            return None
        if not verify_password(password, user.password_hash):
            return None

        if not user.is_active or user.status == "offboarded":
            log.info("Sign-in refused for inactive user id=%s in tenant '%s'", user.id, company.slug)
            return None
        db.expunge(user)
        return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response):
    """Single sign-in for everyone: platform admins and company users. The company is found from the email."""
    ip = request.client.host if request.client else "?"
    email = body.email.lower().strip()
    slug = body.company_slug.lower().strip() if body.company_slug else None
    key = f"{slug or '*'}|{email}|{ip}"
    login_limiter.check(key)

    if slug is None:
        with platform_session() as pdb:
            admin = pdb.scalar(select(PlatformUser).where(func.lower(PlatformUser.email) == email))
            if admin is not None:
                if verify_password(body.password, admin.password_hash):
                    if admin.is_active:
                        login_limiter.reset(key)
                        if admin.mfa_enabled:
                            return _mfa_step(admin.id, "platform_admin", None, admin.session_version)
                        log.info("Platform admin id=%s signed in", admin.id)
                        return _tokens(admin.id, "platform_admin", None, request, response, admin.session_version)

    with platform_session() as pdb:
        q = select(Company).where(Company.status == "active")
        if slug:
            q = q.where(Company.slug == slug)
        else:
            q = q.order_by(Company.id)
        companies = list(pdb.scalars(q))
        pdb.expunge_all()

    matches: list[tuple[Company, User]] = []
    for company in companies:
        try:
            user = _tenant_match(company, email, body.password)
        except Exception as e:
            if "does not exist" in str(e):
                log.warning("Login lookup skipped for company '%s' (id=%d): database does not exist", company.slug, company.id)
            else:
                log.exception("login lookup failed", extra={"tenant_id": company.id})
            continue
        if user is not None:
            matches.append((company, user))

    if not matches:
        burn_password_check(body.password)
        login_limiter.fail(key)
        log.warning("Login failed (company_slug='%s', ip=%s)", slug, ip)
        raise Unauthorized(BAD_CREDS)
    if len(matches) > 1:
        raise AppError("This account exists in more than one company. Please contact your administrator.", status_code=409)
    company, user = matches[0]
    if company.status != "active":
        raise Forbidden("This company account is suspended")
    login_limiter.reset(key)
    if user.mfa_enabled:  # password accepted, no session until the second factor is proven
        log.info("User id=%s passed the password step in tenant %s; MFA required", user.id, company.slug)
        return _mfa_step(user.id, user.role, company.id, user.session_version)
    log.info("User id=%s signed in to tenant %s", user.id, company.slug)
    return _tokens(user.id, user.role, company.id, request, response, user.session_version)


@router.post("/platform/login", response_model=TokenOut)
def platform_login(body: PlatformLoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    key = f"platform|{body.email.lower()}|{ip}"
    login_limiter.check(key)
    with platform_session() as pdb:
        admin = pdb.scalar(select(PlatformUser).where(func.lower(PlatformUser.email) == body.email.lower()))
        if admin is None:
            burn_password_check(body.password)
        valid = admin is not None and admin.is_active and verify_password(body.password, admin.password_hash)
        if not valid:
            login_limiter.fail(key)
            raise Unauthorized(BAD_CREDS)
        login_limiter.reset(key)
        if admin.mfa_enabled:
            return _mfa_step(admin.id, "platform_admin", None, admin.session_version)
        return _tokens(admin.id, "platform_admin", None, request, response, admin.session_version)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, body: RefreshIn | None = None):
    token = body.refresh_token if body else None
    if not token:  # browser session
        token = request.cookies.get(REFRESH_COOKIE)
        if not token:
            raise Unauthorized()
        require_csrf_header(request)
    try:
        claims = decode_token(token, expected_typ="refresh")
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token")
    check_binding(claims, request.cookies.get(DEVICE_COOKIE))
    check_not_revoked(claims)
    if claims.get("role") == "platform_admin":
        with platform_session() as pdb:
            admin = pdb.get(PlatformUser, int(claims["sub"]))
            if admin is None or not admin.is_active:
                raise Unauthorized("Account is disabled")
            check_session_version(claims, admin.session_version)
            out = _tokens(admin.id, "platform_admin", None, request, response, admin.session_version)
        revoke_tokens([token], ("refresh",))  # rotation: each refresh token works once
        return out
    company, db, user = resolve_tenant_user(token, request.cookies.get(DEVICE_COOKIE), expected_typ="refresh")
    db.close()
    out = _tokens(user.id, user.role, company.id, request, response, user.session_version)
    revoke_tokens([token], ("refresh",))  # rotation: each refresh token works once
    return out


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, body: RefreshIn | None = None, creds=Depends(bearer_scheme)):
    """Ends this session: the presented access/refresh tokens are denylisted server-side and the cookies are cleared.
    Needs no auth: presenting a token can only ever revoke that token."""
    access = creds.credentials if creds is not None else request.cookies.get(ACCESS_COOKIE)
    revoke_tokens([access, (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)])
    clear_session(response)


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, ctx: Ctx = Depends(get_ctx)):
    """Sign out everywhere: every token issued so far for this account stops working (all devices)."""
    ctx.user.session_version = (ctx.user.session_version or 0) + 1
    audit(ctx, "auth.logout_all", "user", ctx.user.id)
    ctx.db.commit()
    clear_session(response)


@router.post("/platform/logout-all", status_code=204)
def platform_logout_all(response: Response, who=Depends(get_platform_admin)):
    admin, pdb = who
    admin.session_version = (admin.session_version or 0) + 1
    pdb.commit()
    clear_session(response)


@router.get("/session")
def session(request: Request, creds=Depends(bearer_scheme)):
    """Who is signed in on this browser: works for platform admins and company users alike."""
    token = request_token(request, creds)
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token")
    check_binding(claims, request.cookies.get(DEVICE_COOKIE))
    check_not_revoked(claims)
    if claims.get("role") == "platform_admin" and claims.get("tid") is None:
        with platform_session() as pdb:
            admin = pdb.get(PlatformUser, int(claims["sub"]))
            if admin is None or not admin.is_active:
                raise Unauthorized("Account is disabled")
            check_session_version(claims, admin.session_version)
            return {"role": "platform_admin", "full_name": admin.full_name, "email": admin.email, "mfa_enabled": bool(admin.mfa_enabled),
                    "company": {"name": "WorkSphere Platform"}}
    company, db, user = resolve_tenant_user(token, request.cookies.get(DEVICE_COOKIE))
    db.close()
    return _me_payload(user, company)


def _me_payload(u: User, company: Company | None, slug: str | None = None) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "department_id": u.department_id,
        "branch_id": u.branch_id,
        "designation": u.designation,
        "phone": u.phone,
        "avatar_v": u.avatar_name,
        "mfa_enabled": bool(u.mfa_enabled),
        # what a manager may do; the UI only uses this to hide pages the server would refuse (the server still enforces it)
        "permissions": sorted(k for k in MANAGER_PERMISSIONS if has_permission(u, k)) if u.role == "manager" else None,
        "email_verified": u.email_verified_at is not None,
        "company": {"slug": slug or (company.slug if company else ""), "name": company.name if company else ""},
    }


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    with platform_session() as pdb:
        company = pdb.get(Company, ctx.company_id)
    return _me_payload(ctx.user, company, ctx.company_slug)


@router.patch("/me")
def update_me(body: ProfileUpdate, ctx: Ctx = Depends(get_ctx)):
    data = body.model_dump(exclude_unset=True)
    data = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in data.items()}
    if "full_name" in data and (data["full_name"] is None or len(data["full_name"]) < 2):
        raise AppError("Name must be at least 2 characters")
    for k, v in data.items():
        setattr(ctx.user, k, v)
    audit(ctx, "profile.updated", "user", ctx.user.id, {"fields": sorted(data)})
    ctx.db.commit()
    return me(ctx)


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, request: Request, response: Response, ctx: Ctx = Depends(get_ctx)):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise AppError("Current password is incorrect")
    ctx.user.password_hash = hash_password(body.new_password)
    ctx.user.session_version = (ctx.user.session_version or 0) + 1  # every other session is signed out
    audit(ctx, "auth.password_changed", "user", ctx.user.id)
    ctx.db.commit()
    if is_web_client(request):  # this browser stays signed in with fresh cookies; API clients sign in again
        _tokens(ctx.user.id, ctx.user.role, ctx.company_id, request, response, ctx.user.session_version)
