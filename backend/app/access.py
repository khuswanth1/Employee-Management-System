"""Central authorization helpers: permissions, branch scope and the communication hierarchy.

Scope rules (all enforced server-side; the UI only mirrors them):
- founder: whole company.
- hr: whole company, unless the HR user is assigned to a branch, then only that branch.
- manager: their direct reports (and, when the manager is assigned to a branch, only people of that branch).
- employee: themselves.
- board_member: no employee data at all; only aggregated analytics (see modules/board).
"""
from fastapi import Depends
from sqlalchemy import and_, true
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import Forbidden
from app.db.tenant_models import User
from app.deps import Ctx, get_ctx

# ---- permissions ------------------------------------------------------------------------------

MANAGER_PERMISSIONS = {
    "projects.manage": "Create and manage projects and tasks",
    "leave.approve": "Approve or reject leave requests of direct reports",
    "updates.review": "Review daily updates of direct reports",
    "reports.view": "View team attendance, update and leave reports",
    "attendance.approve": "Approve or reject attendance corrections of direct reports",
    "employees.manage": "View their direct reports and add new employees to their team",
    "teams.manage": "Create teams, assign team leaders and members, and allocate projects to teams",
}
BOARD_PERMISSIONS = {
    "analytics.view": "View company-level analytics",
    "reports.view": "View strategic summary reports",
}


def has_permission(user: User, key: str) -> bool:
    """Managers: explicit list if configured, otherwise every manager permission. Other roles: role rules decide."""
    if user.role == "founder":
        return True
    if user.role == "manager":
        granted = user.permissions if user.permissions is not None else list(MANAGER_PERMISSIONS)
        return key in granted
    return False


def require_permission(key: str, *roles: str):
    """Dependency: caller has one of `roles`, and (for managers) the named permission."""

    def checked(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ctx.role not in roles:
            raise Forbidden()
        if ctx.role == "manager" and not has_permission(ctx.user, key):
            raise Forbidden(f"Your account does not have the '{key}' permission")
        return ctx

    return checked


# ---- branch / user scope ----------------------------------------------------------------------

def user_scope(ctx: Ctx) -> ColumnElement[bool]:
    """SQL condition over `User` listing the people the caller may see/manage as part of their job."""
    u = ctx.user
    if ctx.role == "founder":
        return true()
    if ctx.role == "hr":
        return User.branch_id == u.branch_id if u.branch_id is not None else true()
    if ctx.role == "manager":
        cond = User.manager_id == u.id
        return and_(cond, User.branch_id == u.branch_id) if u.branch_id is not None else cond
    return User.id == u.id


def can_manage_user(ctx: Ctx, target: User) -> bool:
    """Manager/HR/founder administration scope."""
    if ctx.role == "founder":
        return True
    if ctx.role == "hr":
        return ctx.user.branch_id is None or target.branch_id == ctx.user.branch_id
    if ctx.role == "manager":
        # Managers can manage their own direct reports only
        return target.manager_id == ctx.user.id and same_branch(ctx.user, target) and target.role in ("employee", "hr") and target.id != ctx.user.id
    return False


def same_branch(a: User, b: User) -> bool:
    return a.branch_id is None or b.branch_id is None or a.branch_id == b.branch_id


# ---- communication hierarchy ------------------------------------------------------------------

def can_message(a: User, b: User, *, exceptions: set[int]) -> bool:
    """May `a` and `b` hold a direct conversation?

    Employees -> Branch Managers / HR -> Founder. Employee <-> Founder is blocked unless the employee is on the
    founder-managed exception list. Board members talk to the founder and to other board members only.
    """
    if a.id == b.id:
        return False
    pair = {a.role, b.role}
    if "board_member" in pair:
        return pair <= {"board_member", "founder"}
    if "founder" in pair:
        other = b if a.role == "founder" else a
        if other.role == "employee":
            return other.id in exceptions
        return True  # founder <-> manager / hr / founder
    if pair == {"employee"}:
        return same_branch(a, b)  # peers talk within their branch
    if "employee" in pair:  # employee <-> manager / hr, within the branch
        return same_branch(a, b)
    return True  # manager / hr among themselves
