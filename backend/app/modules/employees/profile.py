"""Extended employee profile: employment details (HR-managed), identity details and restricted personal data.

Access rules, all enforced here and mirrored (never replaced) by the UI:
- anyone who may view the employee sees the employment and identity fields;
- restricted fields (personal email, birth date, gender, address, emergency contact) are returned only to the
  person themself and to HR/founders administering that account; managers and everyone else never receive them;
- employment fields can only be written by those who administer the account; the person may edit their own
  identity and restricted fields.
"""
from datetime import date

from fastapi import APIRouter, Depends

from app.common import audit
from app.core.errors import AppError, Forbidden
from app.db.tenant_models import EmployeeProfile
from app.deps import Ctx, get_ctx
from app.modules.employees.router import _can_admin, _can_view, _get_user, employee_staff
from app.modules.employees.schemas import ProfileUpdate

router = APIRouter(tags=["employees"])

EMPLOYMENT_FIELDS = ("employment_type", "employment_category", "job_level", "probation_end_date", "confirmation_date",
                     "notice_period_days", "last_working_date", "tags")
IDENTITY_FIELDS = ("middle_name", "display_name", "skills", "certifications")
RESTRICTED_FIELDS = ("personal_email", "date_of_birth", "gender", "address", "emergency_contact_name",
                     "emergency_contact_relationship", "emergency_contact_phone", "emergency_contact_address")
LISTS = ("skills", "certifications", "tags")


def _sees_restricted(ctx: Ctx, target) -> bool:
    return target.id == ctx.user.id or (ctx.role in ("hr", "founder") and _can_admin(ctx, target))


def _serialize(ctx: Ctx, target, p: EmployeeProfile | None) -> dict:
    restricted = _sees_restricted(ctx, target)
    out: dict = {"user_id": target.id, "can_view_restricted": restricted,
                 "can_edit_employment": ctx.role in ("hr", "founder", "manager") and _can_admin(ctx, target),
                 "updated_at": p.updated_at if p else None}
    for k in EMPLOYMENT_FIELDS + IDENTITY_FIELDS:
        v = getattr(p, k, None) if p else None
        out[k] = [] if v is None and k in LISTS else v
    if restricted:
        for k in RESTRICTED_FIELDS:
            out[k] = getattr(p, k, None) if p else None
    return out


def _check_dates(joined: date | None, merged: dict) -> None:
    for key, label in (("probation_end_date", "Probation end date"), ("confirmation_date", "Confirmation date"), ("last_working_date", "Last working date")):
        d = merged.get(key)
        if d and joined and d < joined:
            raise AppError(f"{label} cannot be before the joining date ({joined.isoformat()})")
    if merged.get("confirmation_date") and merged.get("probation_end_date") and merged["confirmation_date"] < merged["probation_end_date"]:
        raise AppError("Confirmation date cannot be before the probation end date")


@router.get("/employees/{user_id}/profile")
def get_profile(user_id: int, ctx: Ctx = Depends(get_ctx)):
    target = _get_user(ctx, user_id)
    if not _can_view(ctx, target):
        raise Forbidden()
    return _serialize(ctx, target, ctx.db.get(EmployeeProfile, user_id))


@router.patch("/employees/{user_id}/profile")
def update_profile(user_id: int, body: ProfileUpdate, ctx: Ctx = Depends(get_ctx)):
    target = _get_user(ctx, user_id)
    is_self = target.id == ctx.user.id
    admin = ctx.role in ("hr", "founder", "manager") and _can_admin(ctx, target)
    if admin and ctx.role == "manager":
        employee_staff(ctx)  # managers need the 'employees.manage' permission, as for the rest of employee administration
    if not (is_self or admin):
        raise Forbidden()
    data = body.model_dump(exclude_unset=True)
    allowed = set(IDENTITY_FIELDS)
    if _sees_restricted(ctx, target):
        allowed |= set(RESTRICTED_FIELDS)
    if admin:
        allowed |= set(EMPLOYMENT_FIELDS)
    denied = sorted(set(data) - allowed)
    if denied:
        raise Forbidden(f"You cannot change: {', '.join(denied)}")
    p = ctx.db.get(EmployeeProfile, user_id)
    if p is None:
        p = EmployeeProfile(user_id=user_id)
        ctx.db.add(p)
    _check_dates(target.hire_date, {k: data[k] if k in data else getattr(p, k, None) for k in EMPLOYMENT_FIELDS})
    for k, v in data.items():
        setattr(p, k, v)
    p.updated_by = ctx.user.id
    # field names only: restricted values never enter the audit log
    audit(ctx, "employee.profile_updated", "user", user_id, {"fields": sorted(data), "self": is_self})
    ctx.db.commit()
    return _serialize(ctx, target, p)
