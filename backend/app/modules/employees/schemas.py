from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.base import utcnow
from app.core.security import validate_temporary_password

Role = Literal["founder", "hr", "manager", "employee"]


EmployeeCode = Field(None, min_length=3, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]+$")


class EmployeeCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(max_length=200)
    role: Role = "employee"
    department_id: int | None = None
    manager_id: int | None = None
    designation: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)
    hire_date: date | None = None
    employee_code: str | None = EmployeeCode
    branch_id: int | None = None
    location: str | None = Field(None, max_length=120)

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        validate_temporary_password(v)
        return v


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    role: Role | None = None
    department_id: int | None = None
    manager_id: int | None = None
    designation: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)
    hire_date: date | None = None
    status: Literal["onboarding", "active"] | None = None
    employee_code: str | None = EmployeeCode
    branch_id: int | None = None
    location: str | None = Field(None, max_length=120)


class PasswordReset(BaseModel):
    new_password: str = Field(max_length=200)

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        validate_temporary_password(v)
        return v


_DEPT_CODE = r"^[A-Za-z0-9][A-Za-z0-9_-]{1,19}$"


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str | None = Field(None, pattern=_DEPT_CODE)
    description: str | None = Field(None, max_length=1000)
    head_id: int | None = None
    parent_id: int | None = None
    cost_center: str | None = Field(None, max_length=40)
    status: Literal["active", "inactive"] = "active"

    @field_validator("code")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else None

    @field_validator("name", "description", "cost_center")
    @classmethod
    def _strip(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class DepartmentUpdate(BaseModel):
    """Partial update: only the fields sent change."""

    name: str | None = Field(None, min_length=2, max_length=120)
    code: str | None = Field(None, pattern=_DEPT_CODE)
    description: str | None = Field(None, max_length=1000)
    head_id: int | None = None
    parent_id: int | None = None
    cost_center: str | None = Field(None, max_length=40)
    status: Literal["active", "inactive"] | None = None

    _upper = field_validator("code")(classmethod(lambda cls, v: v.upper() if v else None))
    _strip = field_validator("name", "description", "cost_center")(classmethod(lambda cls, v: ((v.strip() or None) if isinstance(v, str) else v)))


class ChecklistUpdate(BaseModel):
    done: bool


EmploymentType = Literal["full_time", "part_time", "contract", "intern", "consultant"]
Gender = Literal["female", "male", "non_binary", "prefer_not_to_say"]
DOC_TYPES = ("resume", "offer_letter", "employment_agreement", "identity", "qualification", "certification", "contract", "other")
_PHONE = r"^[0-9+()\-\s.]{5,40}$"


def _clean_list(v):
    if v is None:
        return None
    seen, out = set(), []
    for item in v:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


class ProfileUpdate(BaseModel):
    """Every field is optional: only the fields sent are changed. Blank strings clear a field."""

    middle_name: str | None = Field(None, max_length=100)
    display_name: str | None = Field(None, max_length=100)
    employment_type: EmploymentType | None = None
    employment_category: str | None = Field(None, max_length=60)
    job_level: str | None = Field(None, max_length=40)
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    notice_period_days: int | None = Field(None, ge=0, le=365)
    last_working_date: date | None = None
    skills: list[str] | None = Field(None, max_length=50)
    certifications: list[str] | None = Field(None, max_length=50)
    tags: list[str] | None = Field(None, max_length=30)
    personal_email: EmailStr | None = None
    date_of_birth: date | None = None
    gender: Gender | None = None
    address: str | None = Field(None, max_length=300)
    emergency_contact_name: str | None = Field(None, max_length=120)
    emergency_contact_relationship: str | None = Field(None, max_length=60)
    emergency_contact_phone: str | None = Field(None, pattern=_PHONE)
    emergency_contact_address: str | None = Field(None, max_length=300)

    @field_validator("skills", "certifications", "tags")
    @classmethod
    def _items(cls, v):
        v = _clean_list(v)
        if v and any(len(i) > 60 for i in v):
            raise ValueError("Each entry must be 60 characters or fewer")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v):
        if v is None:
            return v
        years = (utcnow().date() - v).days / 365.25
        if v >= utcnow().date() or years < 14 or years > 100:
            raise ValueError("Enter a valid date of birth (age 14 to 100)")
        return v

    @field_validator("middle_name", "display_name", "employment_category", "job_level", "address", "emergency_contact_name",
                     "emergency_contact_relationship", "emergency_contact_address", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


class DocumentVerification(BaseModel):
    status: Literal["pending", "verified", "rejected"]
