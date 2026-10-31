from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.common import PageParams, audit, paginate
from app.core.errors import AppError, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import DailyUpdate, User
from app.access import require_permission, same_branch, user_scope
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import notify
from app.modules.teams.service import team_leader_ids_for_user
from app.modules.webhooks.service import emit

router = APIRouter(prefix="/daily-updates", tags=["daily-updates"])
BACKDATE_DAYS = 7


class UpdateIn(BaseModel):
    work_date: date
    completed: str = Field(min_length=1, max_length=5000)
    hours_worked: float = Field(ge=0, le=24)
    pending: str | None = Field(None, max_length=5000)
    blockers: str | None = Field(None, max_length=5000)
    next_plan: str | None = Field(None, max_length=5000)


class ReviewIn(BaseModel):
    status: Literal["reviewed", "needs_changes"]
    comment: str | None = Field(None, max_length=2000)


def ser(u: DailyUpdate, name: str | None = None) -> dict:
    return {
        "id": u.id, "user_id": u.user_id, "user_name": name, "work_date": u.work_date, "completed": u.completed,
        "hours_worked": u.hours_worked, "pending": u.pending, "blockers": u.blockers, "next_plan": u.next_plan,
        "review_status": u.review_status, "review_comment": u.review_comment, "reviewed_by": u.reviewed_by,
        "reviewed_at": u.reviewed_at, "has_blockers": bool(u.blockers and u.blockers.strip()),
    }


@router.post("", status_code=201)
def submit(body: UpdateIn, ctx: Ctx = Depends(get_ctx)):
    today = utcnow().date()
    if body.work_date > today:
        raise AppError("Cannot submit an update for a future date")
    if body.work_date < today - timedelta(days=BACKDATE_DAYS):
        raise AppError(f"Updates can only be submitted for the last {BACKDATE_DAYS} days")
    row = ctx.db.scalar(select(DailyUpdate).where(DailyUpdate.user_id == ctx.user.id, DailyUpdate.work_date == body.work_date))
    created = row is None
    if created:
        row = DailyUpdate(user_id=ctx.user.id, work_date=body.work_date)
        ctx.db.add(row)
    for k in ("completed", "hours_worked", "pending", "blockers", "next_plan"):
        setattr(row, k, getattr(body, k))
    row.review_status, row.review_comment, row.reviewed_by, row.reviewed_at = "pending", None, None, None
    ctx.db.flush()
    if ctx.user.manager_id:
        blockers = " (has blockers)" if row.blockers and row.blockers.strip() else ""
        notify(ctx.db, [ctx.user.manager_id], "Daily update submitted", f"{ctx.user.full_name} – {row.work_date}{blockers}", "daily_update", "/updates/team")
    leaders = [i for i in team_leader_ids_for_user(ctx.db, ctx.user.id) if i != ctx.user.manager_id]
    if leaders:
        blockers = " (has blockers)" if row.blockers and row.blockers.strip() else ""
        notify(ctx.db, leaders, "Daily update submitted", f"{ctx.user.full_name} – {row.work_date}{blockers}", "daily_update", "/teams")
    emit(ctx.db, "daily_update.submitted", {"id": row.id, "user_id": ctx.user.id, "work_date": row.work_date.isoformat()})
    ctx.db.commit()
    return ser(row, ctx.user.full_name)


@router.get("/mine")
def mine(start: date | None = None, end: date | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(DailyUpdate).where(DailyUpdate.user_id == ctx.user.id).order_by(DailyUpdate.work_date.desc())
    if start:
        stmt = stmt.where(DailyUpdate.work_date >= start)
    if end:
        stmt = stmt.where(DailyUpdate.work_date <= end)
    return paginate(ctx.db, stmt, params, lambda u: ser(u, ctx.user.full_name))


@router.get("/team")
def team(
    work_date: date | None = None, user_id: int | None = None, review_status: str | None = None,
    params: PageParams = Depends(), ctx: Ctx = Depends(require_permission("reports.view", "manager", "hr", "founder")),
):
    stmt = select(DailyUpdate).order_by(DailyUpdate.work_date.desc(), DailyUpdate.id.desc())
    if ctx.role != "founder":
        stmt = stmt.join(User, User.id == DailyUpdate.user_id).where(user_scope(ctx))
    if work_date:
        stmt = stmt.where(DailyUpdate.work_date == work_date)
    if user_id:
        stmt = stmt.where(DailyUpdate.user_id == user_id)
    if review_status:
        stmt = stmt.where(DailyUpdate.review_status == review_status)
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    return paginate(ctx.db, stmt, params, lambda u: ser(u, names.get(u.user_id)))


@router.post("/{update_id}/review")
def review(update_id: int, body: ReviewIn, ctx: Ctx = Depends(require_permission("updates.review", "manager"))):
    row = ctx.db.get(DailyUpdate, update_id)
    if row is None:
        raise NotFound()
    author = ctx.db.get(User, row.user_id)
    if author.manager_id != ctx.user.id or not same_branch(ctx.user, author):
        raise Forbidden("You can only review updates from your direct reports")
    row.review_status, row.review_comment, row.reviewed_by, row.reviewed_at = body.status, body.comment, ctx.user.id, utcnow()
    notify(ctx.db, [row.user_id], "Daily update " + ("reviewed" if body.status == "reviewed" else "needs changes"),
           body.comment or str(row.work_date), "daily_update", "/updates")
    audit(ctx, "daily_update.reviewed", "daily_update", row.id, {"status": body.status})
    ctx.db.commit()
    return ser(row, author.full_name)
