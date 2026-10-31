"""Organisation structure managed by the Founder: branches/locations and branch managers."""
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from app.access import MANAGER_PERMISSIONS
from app.common import audit
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.tenant_models import Branch, Department, User
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import notify
from app.modules.teams.service import release_if_branch_mismatch

router = APIRouter(tags=["organisation"])
founder_only = require_roles("founder")
ASSIGNABLE = ("employee", "manager", "hr")  # founders and board members are company-wide


# ---- branches -----------------------------------------------------------------------------------

def _norm_code(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,19}", v):
        raise ValueError("Code may contain letters, digits, '-' and '_'")
    return v


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_PHONE = r"^[0-9+()\-\s.]{5,40}$"


def _tz(v: str | None) -> str | None:
    if not v:
        return None
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("Unknown timezone. Use an IANA name such as Asia/Kolkata or Europe/London") from None
    return v


def _days(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    v = [d.lower() for d in v]
    if not v or any(d not in WEEKDAYS for d in v) or len(set(v)) != len(v):
        raise ValueError("Working days must be unique values from mon to sun, at least one")
    return sorted(v, key=WEEKDAYS.index)


class BranchBase(BaseModel):
    address: str | None = Field(None, max_length=300)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(None, pattern=_PHONE)
    timezone: str | None = Field(None, max_length=64)
    working_days: list[str] | None = Field(None, max_length=7)
    manager_id: int | None = None
    hr_representative_id: int | None = None

    _tz = field_validator("timezone")(classmethod(lambda cls, v: _tz(v)))
    _days = field_validator("working_days")(classmethod(lambda cls, v: _days(v)))


class BranchIn(BranchBase):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=20)

    _code = field_validator("code")(classmethod(lambda cls, v: _norm_code(v)))


class BranchUpdate(BranchBase):
    name: str | None = Field(None, min_length=2, max_length=120)
    code: str | None = Field(None, min_length=2, max_length=20)
    is_active: bool | None = None

    _code = field_validator("code")(classmethod(lambda cls, v: _norm_code(v)))


def ser_branch(ctx: Ctx, b: Branch, counts: dict | None = None) -> dict:
    d = {"id": b.id, "name": b.name, "code": b.code, "address": b.address, "city": b.city, "state": b.state, "country": b.country,
         "postal_code": b.postal_code, "contact_email": b.contact_email, "contact_phone": b.contact_phone, "timezone": b.timezone,
         "working_days": b.working_days, "is_active": b.is_active, "created_at": b.created_at}
    # a manager / HR representative only counts while they are still active members of this branch
    for key, field in (("manager", b.manager_id), ("hr_representative", b.hr_representative_id)):
        u = ctx.db.get(User, field) if field else None
        ok = u is not None and u.is_active and u.branch_id == b.id
        d[f"{key}_id"], d[f"{key}_name"] = (u.id, u.full_name) if ok else (None, None)
    if ctx.role in ("founder", "hr"):
        c = counts if counts is not None else _counts(ctx, [b.id])
        d["counts"] = c.get(b.id, {"employee": 0, "manager": 0, "hr": 0})
    return d


def _check_contacts(ctx: Ctx, b: Branch, data: dict) -> None:
    """Branch manager: a manager or HR in this branch. HR representative: an HR user in this branch."""
    for key, roles, label in (("manager_id", ("manager", "hr"), "branch manager"), ("hr_representative_id", ("hr",), "HR representative")):
        if data.get(key) is None:
            continue
        u = ctx.db.get(User, data[key])
        if u is None or not u.is_active or u.role not in roles or u.branch_id != b.id:
            raise AppError(f"The {label} must be an active {' or '.join(roles)} user already assigned to this branch")


def _counts(ctx: Ctx, ids: list[int]) -> dict:
    rows = ctx.db.execute(select(User.branch_id, User.role, func.count(User.id)).where(
        User.branch_id.in_(ids), User.is_active.is_(True)).group_by(User.branch_id, User.role)).all()
    out: dict[int, dict] = {}
    for bid, role, n in rows:
        out.setdefault(bid, {"employee": 0, "manager": 0, "hr": 0})[role] = n
    return out


def _release_cross_branch_lines(ctx: Ctx, user: User) -> list[int]:
    """Reporting lines never cross branches: drop a line manager / direct reports now in a different branch."""
    released: list[int] = []
    boss = ctx.db.get(User, user.manager_id) if user.manager_id else None
    if boss is not None and boss.branch_id is not None and user.branch_id is not None and boss.branch_id != user.branch_id:
        user.manager_id = None
        released.append(user.id)
    if user.branch_id is not None:
        for rep in ctx.db.scalars(select(User).where(User.manager_id == user.id, User.branch_id.is_not(None), User.branch_id != user.branch_id)):
            rep.manager_id = None
            released.append(rep.id)
    return released


def _get_branch(ctx: Ctx, bid: int) -> Branch:
    b = ctx.db.get(Branch, bid)
    if b is None:
        raise NotFound("Branch not found")
    return b


def _unique(ctx: Ctx, name: str | None, code: str | None, exclude: int | None = None) -> None:
    for col, val, label in ((Branch.name, name, "name"), (Branch.code, code, "code")):
        if val is None:
            continue
        stmt = select(Branch.id).where(func.lower(col) == val.lower())
        if exclude:
            stmt = stmt.where(Branch.id != exclude)
        if ctx.db.scalar(stmt):
            raise Conflict(f"A branch with this {label} already exists")


@router.get("/branches")
def list_branches(ctx: Ctx = Depends(get_ctx)):
    """Any signed-in non-board user may read the branch list (needed by forms); counts are HR/founder only."""
    if ctx.role == "board_member":
        raise Forbidden()
    rows = list(ctx.db.scalars(select(Branch).order_by(Branch.name)))
    counts = _counts(ctx, [b.id for b in rows]) if rows and ctx.role in ("founder", "hr") else {}
    return {"items": [ser_branch(ctx, b, counts) for b in rows]}


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn, ctx: Ctx = Depends(founder_only)):
    _unique(ctx, body.name, body.code)
    data = body.model_dump(exclude={"name", "code", "manager_id", "hr_representative_id"})
    if body.manager_id or body.hr_representative_id:
        raise AppError("Assign people to the branch first, then choose its manager and HR representative")
    b = Branch(name=body.name.strip(), code=body.code, **data)
    ctx.db.add(b)
    ctx.db.flush()
    audit(ctx, "branch.created", "branch", b.id, {"name": b.name, "code": b.code})
    ctx.db.commit()
    return ser_branch(ctx, b)


@router.get("/branches/{bid}")
def branch_detail(bid: int, ctx: Ctx = Depends(get_ctx)):
    if ctx.role == "board_member":
        raise Forbidden()
    b = _get_branch(ctx, bid)
    d = ser_branch(ctx, b)
    if ctx.role in ("founder", "hr") and (ctx.role == "founder" or ctx.user.branch_id in (None, b.id)):
        members = ctx.db.scalars(select(User).where(User.branch_id == b.id, User.is_active.is_(True)).order_by(User.full_name))
        d["members"] = [{"id": u.id, "full_name": u.full_name, "role": u.role, "designation": u.designation, "avatar_v": u.avatar_name} for u in members]
    return d


@router.patch("/branches/{bid}")
def update_branch(bid: int, body: BranchUpdate, ctx: Ctx = Depends(founder_only)):
    b = _get_branch(ctx, bid)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "code", "is_active") and v is None)}
    _unique(ctx, data.get("name"), data.get("code"), exclude=b.id)
    _check_contacts(ctx, b, data)
    for k, v in data.items():
        setattr(b, k, v.strip() if isinstance(v, str) else v)
    audit(ctx, "branch.updated", "branch", b.id, {"fields": sorted(data)})
    ctx.db.commit()
    return ser_branch(ctx, b)


@router.delete("/branches/{bid}", status_code=204)
def delete_branch(bid: int, ctx: Ctx = Depends(founder_only)):
    b = _get_branch(ctx, bid)
    if ctx.db.scalar(select(func.count(User.id)).where(User.branch_id == b.id)):
        raise Conflict("Branch still has people assigned. Move them first, or deactivate the branch instead.")
    ctx.db.delete(b)
    audit(ctx, "branch.deleted", "branch", bid, {"name": b.name})
    ctx.db.commit()


class MembersIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/branches/{bid}/members")
def assign_members(bid: int, body: MembersIn, ctx: Ctx = Depends(founder_only)):
    """Assign employees, HR and managers to this branch (founders and board members are company-wide)."""
    b = _get_branch(ctx, bid)
    if not b.is_active:
        raise AppError("This branch is inactive")
    users = list(ctx.db.scalars(select(User).where(User.id.in_(set(body.user_ids)), User.is_active.is_(True))))
    if len(users) != len(set(body.user_ids)):
        raise AppError("One or more users do not exist or are inactive")
    bad = [u.full_name for u in users if u.role not in ASSIGNABLE]
    if bad:
        raise AppError(f"Founders and board members cannot be assigned to a branch: {', '.join(bad)}")
    released: list[int] = []
    for u in users:
        u.branch_id = b.id
        if not u.location:
            u.location = b.city
    ctx.db.flush()
    for u in users:
        released += _release_cross_branch_lines(ctx, u)
        release_if_branch_mismatch(ctx.db, u)
    notify(ctx.db, [u.id for u in users], "Branch assignment", f"You are now part of the {b.name} branch.", "org")
    audit(ctx, "branch.members_assigned", "branch", b.id, {"user_ids": sorted(u.id for u in users), "released_reporting_lines": sorted(set(released))})
    ctx.db.commit()
    return ser_branch(ctx, b)


@router.delete("/branches/{bid}/members/{user_id}", status_code=204)
def unassign_member(bid: int, user_id: int, ctx: Ctx = Depends(founder_only)):
    _get_branch(ctx, bid)
    u = ctx.db.get(User, user_id)
    if u is None or u.branch_id != bid:
        raise NotFound("That person is not in this branch")
    u.branch_id = None
    ctx.db.flush()
    release_if_branch_mismatch(ctx.db, u)
    audit(ctx, "branch.member_removed", "branch", bid, {"user_id": user_id})
    ctx.db.commit()


# ---- branch managers (founder controlled) ---------------------------------------------------------------

def ser_manager(ctx: Ctx, m: User) -> dict:
    team = ctx.db.scalar(select(func.count(User.id)).where(User.manager_id == m.id, User.is_active.is_(True))) or 0
    granted = m.permissions if m.permissions is not None else list(MANAGER_PERMISSIONS)
    return {"id": m.id, "full_name": m.full_name, "email": m.email, "designation": m.designation, "branch_id": m.branch_id,
            "department_id": m.department_id, "reports_to": m.manager_id, "team_size": team, "permissions": granted,
            "avatar_v": m.avatar_name, "is_active": m.is_active}


@router.get("/managers/permissions-catalog")
def permissions_catalog(ctx: Ctx = Depends(founder_only)):
    return {"items": [{"key": k, "description": d} for k, d in MANAGER_PERMISSIONS.items()]}


@router.get("/managers")
def list_managers(ctx: Ctx = Depends(founder_only)):
    rows = ctx.db.scalars(select(User).where(User.role == "manager").order_by(User.full_name))
    return {"items": [ser_manager(ctx, m) for m in rows]}


def _get_manager(ctx: Ctx, mid: int) -> User:
    m = ctx.db.get(User, mid)
    if m is None or m.role != "manager":
        raise NotFound("Manager not found")
    return m


class ManagerUpdate(BaseModel):
    branch_id: int | None = None
    department_id: int | None = None
    reports_to: int | None = None
    permissions: list[str] | None = None


@router.patch("/managers/{mid}")
def update_manager(mid: int, body: ManagerUpdate, ctx: Ctx = Depends(founder_only)):
    """Configure a branch manager: branch, department, reporting line and permissions."""
    m = _get_manager(ctx, mid)
    data = body.model_dump(exclude_unset=True)
    if "branch_id" in data and data["branch_id"] is not None:
        br = _get_branch(ctx, data["branch_id"])
        if not br.is_active:
            raise AppError("This branch is inactive")
    if data.get("department_id") is not None and ctx.db.get(Department, data["department_id"]) is None:
        raise AppError("Department does not exist")
    if "reports_to" in data and data["reports_to"] is not None:
        boss = ctx.db.get(User, data["reports_to"])
        if boss is None or not boss.is_active or boss.id == m.id:
            raise AppError("Invalid reporting manager")
        cur, seen = boss, set()
        while cur is not None and cur.id not in seen:  # no cycles
            if cur.id == m.id:
                raise AppError("Reporting hierarchy cannot contain a cycle")
            seen.add(cur.id)
            cur = ctx.db.get(User, cur.manager_id) if cur.manager_id else None
    if "permissions" in data:
        perms = data["permissions"]
        unknown = set(perms or []) - set(MANAGER_PERMISSIONS)
        if perms is not None and unknown:
            raise AppError(f"Unknown permission(s): {', '.join(sorted(unknown))}")
        m.permissions = sorted(set(perms)) if perms is not None else None
    if "branch_id" in data:
        m.branch_id = data["branch_id"]
    if "department_id" in data:
        m.department_id = data["department_id"]
    if "reports_to" in data:
        m.manager_id = data["reports_to"]
    released = _release_cross_branch_lines(ctx, m) if "branch_id" in data or "reports_to" in data else []
    audit(ctx, "manager.updated", "user", m.id, {"fields": sorted(data), "released_reporting_lines": released, **({"permissions": m.permissions} if "permissions" in data else {})})
    ctx.db.commit()
    return ser_manager(ctx, m)


class TeamIn(BaseModel):
    user_ids: list[int] = Field(max_length=500)


@router.put("/managers/{mid}/team")
def set_team(mid: int, body: TeamIn, ctx: Ctx = Depends(founder_only)):
    """Replace the manager's direct reports with exactly `user_ids` (employees only; released people lose the line manager)."""
    m = _get_manager(ctx, mid)
    ids = set(body.user_ids)
    people = list(ctx.db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))) if ids else []
    if len(people) != len(ids):
        raise AppError("One or more users do not exist or are inactive")
    for u in people:
        if u.role != "employee":
            raise AppError(f"{u.full_name} is not an employee")
        if m.branch_id is not None and u.branch_id not in (None, m.branch_id):
            raise AppError(f"{u.full_name} belongs to a different branch")
    current = {u.id for u in ctx.db.scalars(select(User).where(User.manager_id == m.id))}
    released = select(User).where(User.manager_id == m.id)
    if ids:
        released = released.where(User.id.not_in(ids))
    for u in ctx.db.scalars(released):
        u.manager_id = None
    for u in people:
        u.manager_id = m.id
    added = ids - current
    notify(ctx.db, list(added), "New line manager", f"{m.full_name} is now your manager.", "team")
    notify(ctx.db, [m.id], "Team updated", f"Your team now has {len(ids)} direct report(s).", "team")
    audit(ctx, "manager.team_set", "user", m.id, {"user_ids": sorted(ids)})
    ctx.db.commit()
    return ser_manager(ctx, m)
