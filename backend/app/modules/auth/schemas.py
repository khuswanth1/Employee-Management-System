from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength


class LoginIn(BaseModel):
    # Optional: normally omitted (the account is found by email). Only needed if the same email+password exists in several companies.
    company_slug: str | None = Field(default=None, min_length=2, max_length=63)
    email: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class PlatformLoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class ProfileUpdate(BaseModel):
    """Fields a person may change on their OWN account (role, department, manager, email stay HR/founder-only)."""
    full_name: str | None = Field(None, min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)


class RefreshIn(BaseModel):
    refresh_token: str | None = None  # browsers omit it: the httpOnly cookie is used


class TokenOut(BaseModel):
    # Browser sessions (X-WS-Client: web) get cookies instead: both tokens are None and `role` tells the SPA who signed in.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    role: str | None = None
    # Password was right but a second factor is needed: no session yet, finish with POST /auth/mfa/verify.
    mfa_required: bool = False
    mfa_token: str | None = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class PasswordResetRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    company_slug: str | None = Field(default=None, min_length=2, max_length=63)


class PasswordResetConfirmIn(BaseModel):
    company_slug: str = Field(min_length=2, max_length=63)
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(max_length=200)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class VerifyEmailConfirmIn(BaseModel):
    company_slug: str = Field(min_length=2, max_length=63)
    token: str = Field(min_length=20, max_length=200)


class MfaVerifyIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=20)  # 6-digit TOTP or a recovery code


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(min_length=6, max_length=20)
