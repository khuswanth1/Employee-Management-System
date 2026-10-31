from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength

RESERVED = {"admin", "api", "www", "platform", "app", "static"}


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    founder_name: str = Field(min_length=2, max_length=200)
    founder_email: EmailStr
    founder_password: str = Field(max_length=200)
    max_users: int = Field(500, ge=1, le=100000)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if v in RESERVED:
            raise ValueError("This company URL name is reserved")
        return v

    @field_validator("founder_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    status: Literal["active", "suspended"] | None = None
    max_users: int | None = Field(None, ge=1, le=100000)


class CompanyOut(BaseModel):
    id: int
    slug: str
    name: str
    status: str
    max_users: int
    created_at: datetime
