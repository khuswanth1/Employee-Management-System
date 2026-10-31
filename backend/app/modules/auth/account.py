"""Account security: password reset and e-mail verification by e-mailed link, and TOTP multi-factor authentication."""
import hashlib
import logging
import secrets
from datetime import timedelta

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import func, select

from app.common import audit
from app.core import mailer, mfa
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Unauthorized
from app.core.ratelimit import login_limiter, reset_request_limiter, token_confirm_limiter
from app.core.security import decode_token, decrypt, encrypt, hash_password, verify_password
from app.core.session import check_not_revoked, check_session_version, is_web_client, revoke_tokens
from app.db.base import as_utc, utcnow
from app.db.platform_models import Company, PlatformUser
from app.db.session import platform_session
from app.db.tenant_models import AuditLog, AuthToken, User
from app.deps import Ctx, get_ctx, get_platform_admin, resolve_tenant_user
from app.modules.auth.router import _tokens
from app.modules.auth.schemas import (MfaCodeIn, MfaDisableIn, MfaVerifyIn, PasswordResetConfirmIn, PasswordResetRequestIn, TokenOut,
                                      VerifyEmailConfirmIn)
from app.tenancy.manager import tenants

log = logging.getLogger("worksphere.account")
router = APIRouter(prefix="/auth", tags=["account security"])
BAD_LINK = "This link is invalid or has expired"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _issue(db, user: User, purpose: str, ttl: timedelta) -> str:
    """Create a single-use token (older unused ones of the same purpose are voided). Returns the raw token."""
    now = utcnow()
    for old in db.scalars(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))):
        old.used_at = now
    raw = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=_hash(raw), expires_at=now + ttl))
    return raw


def _link(path: str, slug: str, raw: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/{path}?company={slug}&token={raw}"


def _active_companies(slug: str | None) -> list[Company]:
    with platform_session() as pdb:
        q = select(Company).where(Company.status == "active")
        if slug:
            q = q.where(Company.slug == slug.lower().strip())
        rows = list(pdb.scalars(q))
        pdb.expunge_all()
    return rows


def _consume(company_slug: str, raw: str, purpose: str):
    """Load a valid unused token and its user inside a tenant session. Returns (db, token, user); caller closes db."""
    companies = _active_companies(company_slug)
    if not companies:
        raise AppError(BAD_LINK)
    db = tenants.session_for(companies[0])
    try:
        tok = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash(raw), AuthToken.purpose == purpose))
        user = db.get(User, tok.user_id) if tok else None
        if tok is None or tok.used_at is not None or as_utc(tok.expires_at) < utcnow() or user is None or not user.is_active or user.status == "offboarded":
            raise AppError(BAD_LINK)
        return db, tok, user
    except Exception:
        db.close()
        raise


# ------------------------------------------------------------------ password reset

def _send_reset_links(email: str, slug: str | None) -> None:
    ttl = timedelta(minutes=get_settings().password_reset_minutes)
    for company in _active_companies(slug):
        try:
            with tenants.session_for(company) as db:
                user = db.scalar(select(User).where(func.lower(User.email) == email))
                if user is None or not user.is_active or user.status == "offboarded":
                    continue
                raw = _issue(db, user, "reset", ttl)
                db.add(AuditLog(actor_id=user.id, action="auth.password_reset_requested", entity_type="user", entity_id=user.id))
                db.commit()
                to, name = user.email, user.full_name
            mailer.send_email(to, "Reset your WorkSphere password",
                              f"Hello {name},\n\nUse this link to choose a new password (valid for {int(ttl.total_seconds() // 60)} minutes, one use):\n"
                              f"{_link('reset-password', company.slug, raw)}\n\nIf you did not ask for this, ignore this e-mail; your password stays unchanged.")
        except Exception:
            log.exception("password reset e-mail failed", extra={"tenant_id": company.id})


@router.post("/password-reset/request", status_code=202)
def password_reset_request(body: PasswordResetRequestIn, request: Request, background: BackgroundTasks):
    """Always answers the same way (202) whether or not the account exists; the work happens after the response."""
    email = body.email.lower().strip()
    ip = _ip(request)
    reset_request_limiter.check(f"{ip}|{email}")
    reset_request_limiter.fail(f"{ip}|{email}")
    background.add_task(_send_reset_links, email, body.company_slug)
    return {"detail": "If an account exists for that address, a reset link has been sent."}


@router.post("/password-reset/confirm", status_code=204)
def password_reset_confirm(body: PasswordResetConfirmIn, request: Request):
    key = f"confirm|{_ip(request)}"
    token_confirm_limiter.check(key)
    try:
        db, tok, user = _consume(body.company_slug, body.token, "reset")
    except AppError:
        token_confirm_limiter.fail(key)
        raise
    try:
        now = utcnow()
        user.password_hash = hash_password(body.new_password)
        user.session_version = (user.session_version or 0) + 1  # every existing session ends
        if user.email_verified_at is None:
            user.email_verified_at = now  # following a link sent to the address proves control of it
        tok.used_at = now
        for other in db.scalars(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == "reset", AuthToken.used_at.is_(None))):
            other.used_at = now
        db.add(AuditLog(actor_id=user.id, action="auth.password_reset_completed", entity_type="user", entity_id=user.id, ip=_ip(request)))
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ e-mail verification

def _send_verification(company_slug: str, email: str, name: str, raw: str) -> None:
    mailer.send_email(email, "Confirm your WorkSphere e-mail address",
                      f"Hello {name},\n\nConfirm this e-mail address with the link below (one use):\n{_link('verify-email', company_slug, raw)}\n")


@router.post("/verify-email/request", status_code=202)
def verify_email_request(background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    if ctx.user.email_verified_at is not None:
        raise Conflict("Your e-mail address is already verified")
    recent = ctx.db.scalar(select(func.count(AuthToken.id)).where(AuthToken.user_id == ctx.user.id, AuthToken.purpose == "verify",
                                                                  AuthToken.created_at > utcnow() - timedelta(minutes=1)))
    if recent:
        raise AppError("A verification e-mail was just sent. Please wait a minute.", status_code=429, code="rate_limited")
    raw = _issue(ctx.db, ctx.user, "verify", timedelta(hours=get_settings().email_verify_hours))
    ctx.db.commit()
    background.add_task(_send_verification, ctx.company_slug, ctx.user.email, ctx.user.full_name, raw)
    return {"detail": "Verification e-mail sent."}


@router.post("/verify-email/confirm", status_code=204)
def verify_email_confirm(body: VerifyEmailConfirmIn, request: Request):
    key = f"confirm|{_ip(request)}"
    token_confirm_limiter.check(key)
    try:
        db, tok, user = _consume(body.company_slug, body.token, "verify")
    except AppError:
        token_confirm_limiter.fail(key)
        raise
    try:
        tok.used_at = user.email_verified_at = utcnow()
        db.add(AuditLog(actor_id=user.id, action="auth.email_verified", entity_type="user", entity_id=user.id, ip=_ip(request)))
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ MFA (TOTP)

def check_second_factor(user: User, code: str) -> bool:
    """Accept a current TOTP code (each time step only once) or an unused recovery code. Mutates `user`; caller commits."""
    if not user.mfa_enabled or not user.mfa_secret_enc:
        return False
    step = mfa.verify_totp(decrypt(user.mfa_secret_enc), code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return True
    remaining = mfa.consume_recovery(user.mfa_recovery, code)
    if remaining is None:
        return False
    user.mfa_recovery = remaining
    return True


@router.post("/mfa/verify", response_model=TokenOut)
def mfa_verify(body: MfaVerifyIn, request: Request, response: Response):
    """Second step of sign-in: trade the short-lived `mfa_token` from /auth/login plus a code for a real session."""
    try:
        claims = decode_token(body.mfa_token, expected_typ="mfa")
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token")
    if claims.get("role") == "platform_admin" and claims.get("tid") is None:
        return _platform_mfa_verify(body, claims, request, response)
    company, db, user = resolve_tenant_user(body.mfa_token, None, expected_typ="mfa")
    key = f"mfa|{company.id}|{user.id}"
    try:
        login_limiter.check(key)  # keyed by account, so asking for a fresh mfa_token does not reset the count
        if not check_second_factor(user, body.code):
            login_limiter.fail(key)
            db.add(AuditLog(actor_id=user.id, action="auth.mfa_failed", entity_type="user", entity_id=user.id, ip=_ip(request)))
            db.commit()
            raise AppError("Invalid verification code", code="invalid_code")
        db.add(AuditLog(actor_id=user.id, action="auth.mfa_passed", entity_type="user", entity_id=user.id, ip=_ip(request)))
        db.commit()
        login_limiter.reset(key)
        out = _tokens(user.id, user.role, company.id, request, response, user.session_version)
    finally:
        db.close()
    revoke_tokens([body.mfa_token], ("mfa",))  # the mfa_token works once
    return out


@router.post("/mfa/setup")
def mfa_setup(ctx: Ctx = Depends(get_ctx)):
    """Start enrolment: returns a new secret (and otpauth:// URI for authenticator apps). MFA is not active until /mfa/enable."""
    if ctx.user.mfa_enabled:
        raise Conflict("Two-step verification is already on")
    secret = mfa.new_secret()
    ctx.user.mfa_secret_enc = encrypt(secret)
    ctx.db.commit()
    return {"secret": secret, "otpauth_uri": mfa.otpauth_uri(secret, ctx.user.email)}


@router.post("/mfa/enable")
def mfa_enable(body: MfaCodeIn, ctx: Ctx = Depends(get_ctx)):
    u = ctx.user
    if u.mfa_enabled:
        raise Conflict("Two-step verification is already on")
    if not u.mfa_secret_enc:
        raise AppError("Start set-up first")
    step = mfa.verify_totp(decrypt(u.mfa_secret_enc), body.code)
    if step is None:
        raise AppError("Invalid verification code", code="invalid_code")
    plain, hashed = mfa.new_recovery_codes()
    u.mfa_enabled, u.mfa_last_step, u.mfa_recovery = True, step, hashed
    audit(ctx, "auth.mfa_enabled", "user", u.id)
    ctx.db.commit()
    return {"recovery_codes": plain}  # shown once; only hashes are stored


@router.post("/mfa/disable", status_code=204)
def mfa_disable(body: MfaDisableIn, request: Request, response: Response, ctx: Ctx = Depends(get_ctx)):
    u = ctx.user
    if not u.mfa_enabled:
        raise Conflict("Two-step verification is not on")
    key = f"mfa|{ctx.company_id}|{u.id}"
    login_limiter.check(key)
    if not verify_password(body.password, u.password_hash) or not check_second_factor(u, body.code):
        login_limiter.fail(key)
        ctx.db.rollback()
        raise AppError("Password or verification code is incorrect", code="invalid_code")
    login_limiter.reset(key)
    u.mfa_enabled, u.mfa_secret_enc, u.mfa_last_step, u.mfa_recovery = False, None, None, None
    u.session_version = (u.session_version or 0) + 1
    audit(ctx, "auth.mfa_disabled", "user", u.id)
    ctx.db.commit()
    if is_web_client(request):
        _tokens(u.id, u.role, ctx.company_id, request, response, u.session_version)


# ------------------------------------------------------------------ MFA for platform administrators

def _platform_mfa_verify(body: MfaVerifyIn, claims: dict, request: Request, response: Response) -> TokenOut:
    check_not_revoked(claims)
    with platform_session() as pdb:
        admin = pdb.get(PlatformUser, int(claims["sub"]))
        if admin is None or not admin.is_active:
            raise Unauthorized("Account is disabled")
        check_session_version(claims, admin.session_version)
        key = f"mfa|platform|{admin.id}"
        login_limiter.check(key)
        if not check_second_factor(admin, body.code):
            login_limiter.fail(key)
            raise AppError("Invalid verification code", code="invalid_code")
        pdb.commit()
        login_limiter.reset(key)
        out = _tokens(admin.id, "platform_admin", None, request, response, admin.session_version)
    revoke_tokens([body.mfa_token], ("mfa",))
    return out


@router.post("/platform/mfa/setup")
def platform_mfa_setup(who=Depends(get_platform_admin)):
    admin, pdb = who
    if admin.mfa_enabled:
        raise Conflict("Two-step verification is already on")
    secret = mfa.new_secret()
    admin.mfa_secret_enc = encrypt(secret)
    pdb.commit()
    return {"secret": secret, "otpauth_uri": mfa.otpauth_uri(secret, admin.email, "WorkSphere Platform")}


@router.post("/platform/mfa/enable")
def platform_mfa_enable(body: MfaCodeIn, who=Depends(get_platform_admin)):
    admin, pdb = who
    if admin.mfa_enabled:
        raise Conflict("Two-step verification is already on")
    if not admin.mfa_secret_enc:
        raise AppError("Start set-up first")
    step = mfa.verify_totp(decrypt(admin.mfa_secret_enc), body.code)
    if step is None:
        raise AppError("Invalid verification code", code="invalid_code")
    plain, hashed = mfa.new_recovery_codes()
    admin.mfa_enabled, admin.mfa_last_step, admin.mfa_recovery = True, step, hashed
    pdb.commit()
    log.info("Platform admin id=%s turned on two-step verification", admin.id)
    return {"recovery_codes": plain}


@router.post("/platform/mfa/disable", status_code=204)
def platform_mfa_disable(body: MfaDisableIn, request: Request, response: Response, who=Depends(get_platform_admin)):
    admin, pdb = who
    if not admin.mfa_enabled:
        raise Conflict("Two-step verification is not on")
    key = f"mfa|platform|{admin.id}"
    login_limiter.check(key)
    if not verify_password(body.password, admin.password_hash) or not check_second_factor(admin, body.code):
        login_limiter.fail(key)
        pdb.rollback()
        raise AppError("Password or verification code is incorrect", code="invalid_code")
    login_limiter.reset(key)
    admin.mfa_enabled, admin.mfa_secret_enc, admin.mfa_last_step, admin.mfa_recovery = False, None, None, None
    admin.session_version = (admin.session_version or 0) + 1
    pdb.commit()
    log.info("Platform admin id=%s turned off two-step verification", admin.id)
    if is_web_client(request):
        _tokens(admin.id, "platform_admin", None, request, response, admin.session_version)
