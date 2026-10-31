"""Performance management: rating scales, review cycles, goals and KPIs, self + manager appraisals, continuous feedback, reports.

Confidentiality rules (enforced here):
* goals and reviews are visible to their owner, the owner's line manager, and HR / founders in scope; colleagues never see them;
* a person's draft self-review is private until submitted; the manager's rating and comments stay hidden from the person until the
  manager submits (status `completed`);
* the manager writes the manager part only after the self-review was submitted; nobody edits a review once its cycle is closed;
* founders and board members are not part of review cycles.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select

from app.access import same_branch, user_scope
from app.common import PageParams, audit, paginate, to_csv
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.tenant_models import (Department, Feedback, Goal, GoalUpdate, PerformanceCycle, PerformanceReview, RatingLevel, RatingScale, User)
from app.deps import Ctx, get_ctx, require_roles
from app.modules.notifications.service import notify
from app.modules.performance import rules

router = APIRouter(prefix="/performance", tags=["performance"])
staff = require_roles("hr", "founder")
REVIEWED = ("employee", "manager", "hr")        # roles that take part in review cycles
OPEN = ("draft", "active")


# ================================================================== helpers

def is_staff(ctx: Ctx) -> bool:
    return ctx.role in ("hr", "founder")


def can_see_person(ctx: Ctx, u: User) -> bool:
    if u.id == ctx.user.id:
        return True
    if ctx.role == "founder":
        return u.role in REVIEWED
    if ctx.role == "hr":
        return u.role in REVIEWED and bool(ctx.db.scalar(select(User.id).where(User.id == u.id, user_scope(ctx))))
    if ctx.role == "manager":
        return u.manager_id == ctx.user.id and same_branch(ctx.user, u)
    return False


def person(ctx: Ctx, user_id: int | None) -> User:
    u = ctx.db.get(User, user_id) if user_id else ctx.user
    if u is None or not can_see_person(ctx, u):
        raise NotFound("Person not found")
    return u


def manages(ctx: Ctx, u: User) -> bool:
    """May the caller act on someone's goals / reviews as their manager (not as themselves)?"""
    return u.id != ctx.user.id and can_see_person(ctx, u)


def scale_for(db, scale_id: int) -> RatingScale:
    return db.get(RatingScale, scale_id)


def ensure_default_scale(db) -> None:
    if db.scalar(select(RatingScale.id).limit(1)) is None:
        s = RatingScale(name="Standard 5-point")
        for v, label, d in ((1, "Needs improvement", "Performance is below what the role needs"), (2, "Partially meets", "Meets some expectations"),
                            (3, "Meets expectations", "Does the job well"), (4, "Exceeds expectations", "Regularly goes beyond the role"),
                            (5, "Outstanding", "Exceptional, a model for others")):
            s.levels.append(RatingLevel(value=v, label=label, description=d))
        db.add(s)
        db.flush()


def allowed_values(db, cycle: PerformanceCycle) -> list[int]:
    return [lv.value for lv in scale_for(db, cycle.scale_id).levels]


def check_rating(value: int | None, allowed: list[int], what: str) -> None:
    if value is not None and value not in allowed:
        raise AppError(f"{what} must be one of {', '.join(map(str, allowed))}", status_code=422)


def open_cycle(db, cycle_id: int) -> PerformanceCycle:
    c = db.get(PerformanceCycle, cycle_id)
    if c is None:
        raise NotFound("Review cycle not found")
    if c.status == "closed":
        raise Conflict("This review cycle is closed")
    return c


# ================================================================== rating scales

class LevelIn(BaseModel):
    value: int = Field(ge=1, le=100)
    label: str = Field(min_length=1, max_length=60)
    description: str | None = Field(None, max_length=300)


class ScaleIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    levels: list[LevelIn] = Field(min_length=2, max_length=10)


def ser_scale(s: RatingScale) -> dict:
    return {"id": s.id, "name": s.name, "is_active": s.is_active, "levels": [{"value": lv.value, "label": lv.label, "description": lv.description} for lv in s.levels]}


@router.get("/scales")
def scales(ctx: Ctx = Depends(get_ctx)):
    ensure_default_scale(ctx.db)
    ctx.db.commit()
    return {"items": [ser_scale(s) for s in ctx.db.scalars(select(RatingScale).order_by(RatingScale.id))]}


@router.post("/scales", status_code=201)
def create_scale(body: ScaleIn, ctx: Ctx = Depends(staff)):
    err = rules.validate_levels([(lv.value, lv.label) for lv in body.levels])
    if err:
        raise AppError(err, status_code=422)
    if ctx.db.scalar(select(RatingScale.id).where(func.lower(RatingScale.name) == body.name.lower())):
        raise Conflict("A rating scale with this name already exists")
    s = RatingScale(name=body.name.strip())
    for lv in sorted(body.levels, key=lambda x: x.value):
        s.levels.append(RatingLevel(value=lv.value, label=lv.label.strip(), description=lv.description))
    ctx.db.add(s)
    ctx.db.flush()
    audit(ctx, "performance.scale_created", "rating_scale", s.id)
    ctx.db.commit()
    return ser_scale(s)


@router.post("/scales/{sid}/active")
def set_scale_active(sid: int, active: bool, ctx: Ctx = Depends(staff)):
    s = ctx.db.get(RatingScale, sid)
    if s is None:
        raise NotFound()
    s.is_active = active
    audit(ctx, "performance.scale_toggled", "rating_scale", s.id, {"active": active})
    ctx.db.commit()
    return ser_scale(s)


# ================================================================== cycles

class CycleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    start_date: date
    end_date: date
    self_review_due: date | None = None
    manager_review_due: date | None = None
    scale_id: int | None = None
    competencies: list[str] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("The cycle must end after it starts")
        if self.self_review_due and self.manager_review_due and self.manager_review_due < self.self_review_due:
            raise ValueError("Manager reviews cannot be due before self reviews")
        names = [c.strip() for c in self.competencies]
        if any(not n or len(n) > 80 for n in names) or len({n.lower() for n in names}) != len(names):
            raise ValueError("Competencies must be distinct, non-empty names of at most 80 characters")
        self.competencies = names
        return self


def ser_cycle(ctx: Ctx, c: PerformanceCycle, counts: bool = False) -> dict:
    out = {"id": c.id, "name": c.name, "start_date": c.start_date, "end_date": c.end_date, "self_review_due": c.self_review_due,
           "manager_review_due": c.manager_review_due, "competencies": c.competencies or [], "status": c.status, "scale": ser_scale(scale_for(ctx.db, c.scale_id)),
           "activated_at": c.activated_at, "closed_at": c.closed_at}
    if counts:
        rows = ctx.db.execute(select(PerformanceReview.status, func.count()).where(PerformanceReview.cycle_id == c.id).group_by(PerformanceReview.status)).all()
        out["review_counts"] = {k: n for k, n in rows}
    return out


@router.get("/cycles")
def list_cycles(ctx: Ctx = Depends(get_ctx)):
    ensure_default_scale(ctx.db)
    q = select(PerformanceCycle).order_by(PerformanceCycle.start_date.desc(), PerformanceCycle.id.desc())
    if not is_staff(ctx):
        mine = select(PerformanceReview.cycle_id).where(or_(PerformanceReview.user_id == ctx.user.id, PerformanceReview.reviewer_id == ctx.user.id))
        q = q.where(PerformanceCycle.status != "draft", PerformanceCycle.id.in_(mine))
    ctx.db.commit()
    return {"items": [ser_cycle(ctx, c, counts=is_staff(ctx)) for c in ctx.db.scalars(q)]}


@router.post("/cycles", status_code=201)
def create_cycle(body: CycleIn, ctx: Ctx = Depends(staff)):
    ensure_default_scale(ctx.db)
    scale = ctx.db.get(RatingScale, body.scale_id) if body.scale_id else ctx.db.scalar(select(RatingScale).where(RatingScale.is_active.is_(True)).order_by(RatingScale.id))
    if scale is None or not scale.is_active:
        raise AppError("Choose an active rating scale")
    if ctx.db.scalar(select(PerformanceCycle.id).where(func.lower(PerformanceCycle.name) == body.name.lower())):
        raise Conflict("A cycle with this name already exists")
    c = PerformanceCycle(name=body.name.strip(), start_date=body.start_date, end_date=body.end_date, self_review_due=body.self_review_due,
                         manager_review_due=body.manager_review_due, scale_id=scale.id, competencies=body.competencies, created_by=ctx.user.id)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "performance.cycle_created", "performance_cycle", c.id)
    ctx.db.commit()
    return ser_cycle(ctx, c, counts=True)


@router.patch("/cycles/{cid}")
def update_cycle(cid: int, body: CycleIn, ctx: Ctx = Depends(staff)):
    c = open_cycle(ctx.db, cid)
    if c.status == "active" and (body.scale_id not in (None, c.scale_id) or (body.competencies or []) != (c.competencies or [])):
        raise Conflict("The rating scale and competencies cannot change once the cycle has started")
    if ctx.db.scalar(select(PerformanceCycle.id).where(func.lower(PerformanceCycle.name) == body.name.lower(), PerformanceCycle.id != cid)):
        raise Conflict("A cycle with this name already exists")
    c.name, c.self_review_due, c.manager_review_due = body.name.strip(), body.self_review_due, body.manager_review_due
    if c.status == "draft":
        c.start_date, c.end_date, c.competencies = body.start_date, body.end_date, body.competencies
        if body.scale_id:
            if ctx.db.get(RatingScale, body.scale_id) is None:
                raise AppError("Unknown rating scale")
            c.scale_id = body.scale_id
    audit(ctx, "performance.cycle_updated", "performance_cycle", c.id)
    ctx.db.commit()
    return ser_cycle(ctx, c, counts=True)


@router.delete("/cycles/{cid}", status_code=204)
def delete_cycle(cid: int, ctx: Ctx = Depends(staff)):
    c = ctx.db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound()
    if c.status != "draft":
        raise Conflict("Only a cycle that has not started can be deleted")
    ctx.db.delete(c)
    audit(ctx, "performance.cycle_deleted", "performance_cycle", cid)
    ctx.db.commit()


@router.post("/cycles/{cid}/activate")
def activate_cycle(cid: int, ctx: Ctx = Depends(staff)):
    """Start the cycle: a review is opened for every active employee, manager and HR person who joined before it ends."""
    c = ctx.db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound("Review cycle not found")
    if c.status != "draft":
        raise Conflict(f"This cycle is already {c.status}")
    people = [u for u in ctx.db.scalars(select(User).where(User.is_active.is_(True), User.role.in_(REVIEWED), User.status != "pending_approval"))
              if u.hire_date is None or u.hire_date <= c.end_date]
    if not people:
        raise AppError("There is nobody to review")
    for u in people:
        ctx.db.add(PerformanceReview(cycle_id=c.id, user_id=u.id, reviewer_id=u.manager_id))
    c.status, c.activated_at = "active", utcnow()
    audit(ctx, "performance.cycle_activated", "performance_cycle", c.id, {"reviews": len(people)})
    notify(ctx.db, [u.id for u in people], "Performance review started", f"{c.name}: agree your goals and complete your self review"
           + (f" by {c.self_review_due}" if c.self_review_due else ""), "performance", "/performance")
    ctx.db.commit()
    return ser_cycle(ctx, c, counts=True)


@router.post("/cycles/{cid}/close")
def close_cycle(cid: int, ctx: Ctx = Depends(staff)):
    c = ctx.db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound()
    if c.status != "active":
        raise Conflict("Only an active cycle can be closed")
    c.status, c.closed_at = "closed", utcnow()
    audit(ctx, "performance.cycle_closed", "performance_cycle", c.id)
    ctx.db.commit()
    return ser_cycle(ctx, c, counts=True)


@router.post("/cycles/{cid}/remind")
def remind(cid: int, ctx: Ctx = Depends(staff)):
    """Nudge people whose part is still open: employees who have not submitted, managers who have reviews waiting."""
    c = open_cycle(ctx.db, cid)
    if c.status != "active":
        raise Conflict("The cycle has not started")
    rs = list(ctx.db.scalars(select(PerformanceReview).where(PerformanceReview.cycle_id == cid, PerformanceReview.status.in_(("pending_self", "pending_manager")))))
    selfs = sorted({r.user_id for r in rs if r.status == "pending_self"})
    waiting: dict[int, int] = {}
    for r in rs:
        if r.status == "pending_manager" and r.reviewer_id:
            waiting[r.reviewer_id] = waiting.get(r.reviewer_id, 0) + 1
    notify(ctx.db, selfs, "Self review reminder", f"{c.name}: please submit your self review", "performance", "/performance")
    for rid, n in waiting.items():
        notify(ctx.db, [rid], "Reviews waiting for you", f"{c.name}: {n} review(s) need your assessment", "performance", "/performance")
    audit(ctx, "performance.reminders_sent", "performance_cycle", c.id, {"people": len(selfs) + len(waiting)})
    ctx.db.commit()
    return {"employees": len(selfs), "managers": len(waiting)}


# ================================================================== goals & KPIs

class GoalIn(BaseModel):
    cycle_id: int
    user_id: int | None = None
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(None, max_length=4000)
    kind: Literal["goal", "kpi"] = "goal"
    weight: int = Field(0, ge=0, le=100)
    unit: str | None = Field(None, max_length=30)
    target_value: float | None = Field(None, gt=0)
    due_date: date | None = None

    @model_validator(mode="after")
    def _kpi(self):
        if self.kind == "kpi" and self.target_value is None:
            raise ValueError("A KPI needs a target value")
        return self


class GoalPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=4000)
    weight: int | None = Field(None, ge=0, le=100)
    unit: str | None = Field(None, max_length=30)
    target_value: float | None = Field(None, gt=0)
    due_date: date | None = None


class GoalUpdateIn(BaseModel):
    progress: int | None = Field(None, ge=0, le=100)
    current_value: float | None = Field(None, ge=0)
    comment: str | None = Field(None, max_length=2000)


def ser_goal(g: Goal, names: dict | None = None) -> dict:
    names = names if names is not None else {}
    return {"id": g.id, "cycle_id": g.cycle_id, "user_id": g.user_id, "title": g.title, "description": g.description, "kind": g.kind, "weight": g.weight,
            "unit": g.unit, "target_value": g.target_value, "current_value": g.current_value, "progress": g.progress, "due_date": g.due_date, "status": g.status,
            "created_by": names.get(g.created_by), "agreed_by": names.get(g.agreed_by), "agreed_at": g.agreed_at}


def _names(ctx: Ctx) -> dict:
    return {x.id: x.full_name for x in ctx.db.scalars(select(User))}


def _weights(db, cycle_id: int, user_id: int, exclude: int | None = None) -> list[int]:
    q = select(Goal.weight).where(Goal.cycle_id == cycle_id, Goal.user_id == user_id, Goal.status != "cancelled")
    if exclude:
        q = q.where(Goal.id != exclude)
    return list(db.scalars(q))


def _goal(ctx: Ctx, gid: int) -> tuple[Goal, User]:
    g = ctx.db.get(Goal, gid)
    if g is None:
        raise NotFound("Goal not found")
    return g, person(ctx, g.user_id)


@router.get("/goals")
def list_goals(cycle_id: int, user_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    u = person(ctx, user_id)
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    rows = ctx.db.scalars(select(Goal).where(Goal.cycle_id == cycle_id, Goal.user_id == u.id).order_by(Goal.id))
    items = [ser_goal(g, names) for g in rows]
    agreed = [g["weight"] for g in items if g["status"] != "cancelled"]
    return {"user": {"id": u.id, "name": u.full_name}, "items": items, "total_weight": rules.total_weight(agreed)}


@router.post("/goals", status_code=201)
def create_goal(body: GoalIn, ctx: Ctx = Depends(get_ctx)):
    c = open_cycle(ctx.db, body.cycle_id)
    u = person(ctx, body.user_id)
    if u.role not in REVIEWED:
        raise AppError("Goals are set for employees, managers and HR")
    if not rules.weights_fit(_weights(ctx.db, c.id, u.id), body.weight):
        raise AppError(f"Weights add up to more than 100% ({rules.total_weight(_weights(ctx.db, c.id, u.id))}% already used)", code="weight_exceeded")
    own = u.id == ctx.user.id
    # a goal you set for yourself waits for your manager to agree it, unless you have no manager; goals set by a manager / HR are agreed at once
    agreed = (not own) or u.manager_id is None
    g = Goal(cycle_id=c.id, user_id=u.id, title=body.title.strip(), description=body.description, kind=body.kind, weight=body.weight, unit=body.unit,
             target_value=body.target_value, due_date=body.due_date, current_value=0 if body.kind == "kpi" else None, created_by=ctx.user.id,
             status="agreed" if agreed else "proposed", agreed_by=ctx.user.id if agreed else None, agreed_at=utcnow() if agreed else None)
    ctx.db.add(g)
    ctx.db.flush()
    audit(ctx, "performance.goal_created", "goal", g.id, {"user_id": u.id})
    if own and not agreed:
        notify(ctx.db, [u.manager_id], "Goal to agree", f"{u.full_name} proposed: {g.title}", "performance", "/performance")
    elif not own:
        notify(ctx.db, [u.id], "New goal set for you", g.title, "performance", "/performance")
    ctx.db.commit()
    return ser_goal(g, _names(ctx))


@router.patch("/goals/{gid}")
def edit_goal(gid: int, body: GoalPatch, ctx: Ctx = Depends(get_ctx)):
    g, u = _goal(ctx, gid)
    open_cycle(ctx.db, g.cycle_id)
    if g.status == "cancelled":
        raise Conflict("This goal was cancelled")
    own = u.id == ctx.user.id
    if own and g.status == "agreed" and u.manager_id is not None:
        raise Forbidden("An agreed goal can only be changed by your manager")
    data = body.model_dump(exclude_unset=True)
    if "weight" in data and not rules.weights_fit(_weights(ctx.db, g.cycle_id, g.user_id, exclude=g.id), data["weight"]):
        raise AppError("Weights add up to more than 100%", code="weight_exceeded")
    if g.kind == "goal" and data.get("target_value") is not None:
        raise AppError("Only a KPI has a target value", status_code=422)
    for k, v in data.items():
        setattr(g, k, v.strip() if isinstance(v, str) else v)
    if g.kind == "kpi":
        g.progress = rules.kpi_progress(g.current_value, g.target_value)
    if own and g.status == "proposed":
        pass  # still waiting for the manager
    audit(ctx, "performance.goal_updated", "goal", g.id, {"fields": sorted(data)})
    ctx.db.commit()
    return ser_goal(g, _names(ctx))


@router.post("/goals/{gid}/agree")
def agree_goal(gid: int, ctx: Ctx = Depends(get_ctx)):
    g, u = _goal(ctx, gid)
    open_cycle(ctx.db, g.cycle_id)
    if not manages(ctx, u):
        raise Forbidden("Only the person's manager or HR can agree a goal")
    if g.status != "proposed":
        raise Conflict(f"This goal is already {g.status}")
    g.status, g.agreed_by, g.agreed_at = "agreed", ctx.user.id, utcnow()
    audit(ctx, "performance.goal_agreed", "goal", g.id)
    notify(ctx.db, [u.id], "Goal agreed", g.title, "performance", "/performance")
    ctx.db.commit()
    return ser_goal(g, _names(ctx))


@router.delete("/goals/{gid}", status_code=204)
def cancel_goal(gid: int, ctx: Ctx = Depends(get_ctx)):
    g, u = _goal(ctx, gid)
    open_cycle(ctx.db, g.cycle_id)
    if u.id == ctx.user.id and not (g.status == "proposed" and g.created_by == ctx.user.id):
        raise Forbidden("You can withdraw a goal you proposed that is not yet agreed; ask your manager to cancel an agreed one")
    g.status = "cancelled"
    audit(ctx, "performance.goal_cancelled", "goal", g.id)
    ctx.db.commit()


@router.post("/goals/{gid}/updates", status_code=201)
def add_update(gid: int, body: GoalUpdateIn, ctx: Ctx = Depends(get_ctx)):
    """A progress check-in by the owner or their manager. Goals get a 0-100 progress; KPIs get a current value."""
    g, u = _goal(ctx, gid)
    c = open_cycle(ctx.db, g.cycle_id)
    if c.status != "active":
        raise Conflict("Progress is recorded once the cycle has started")
    if g.status != "agreed":
        raise Conflict("Progress can only be recorded on an agreed goal")
    if g.kind == "kpi":
        if body.current_value is None:
            raise AppError("Enter the current value", status_code=422)
        g.current_value = body.current_value
        g.progress = rules.kpi_progress(g.current_value, g.target_value)
    else:
        if body.progress is None:
            raise AppError("Enter the progress (0-100)", status_code=422)
        g.progress = body.progress
    ctx.db.add(GoalUpdate(goal_id=g.id, author_id=ctx.user.id, progress=g.progress, current_value=g.current_value, comment=body.comment))
    audit(ctx, "performance.goal_progress", "goal", g.id)
    if u.id != ctx.user.id:
        notify(ctx.db, [u.id], "Goal progress updated", g.title, "performance", "/performance")
    ctx.db.commit()
    return ser_goal(g, _names(ctx))


@router.get("/goals/{gid}/updates")
def goal_updates(gid: int, ctx: Ctx = Depends(get_ctx)):
    g, _ = _goal(ctx, gid)
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    rows = ctx.db.scalars(select(GoalUpdate).where(GoalUpdate.goal_id == g.id).order_by(GoalUpdate.id.desc()))
    return {"items": [{"id": x.id, "author": names.get(x.author_id), "progress": x.progress, "current_value": x.current_value, "comment": x.comment, "created_at": x.created_at} for x in rows]}


# ================================================================== reviews

class SelfIn(BaseModel):
    rating: int | None = None
    comments: str | None = Field(None, max_length=6000)
    competencies: dict[str, int] = Field(default_factory=dict)
    goals: dict[int, int] = Field(default_factory=dict)


class ManagerIn(BaseModel):
    rating: int | None = None
    comments: str | None = Field(None, max_length=6000)
    strengths: str | None = Field(None, max_length=4000)
    development_areas: str | None = Field(None, max_length=4000)
    competencies: dict[str, int] = Field(default_factory=dict)
    goals: dict[int, int] = Field(default_factory=dict)


class AckIn(BaseModel):
    response: str | None = Field(None, max_length=4000)


class ReassignIn(BaseModel):
    reviewer_id: int


def can_review(ctx: Ctx, r: PerformanceReview, subject: User) -> bool:
    """Who writes the manager part: the reviewer named when the cycle started; HR / founders in scope when there is none or they left."""
    if subject.id == ctx.user.id:
        return False
    if r.reviewer_id == ctx.user.id:
        return True
    reviewer = ctx.db.get(User, r.reviewer_id) if r.reviewer_id else None
    return is_staff(ctx) and (reviewer is None or not reviewer.is_active) and can_see_person(ctx, subject)


def _review(ctx: Ctx, rid: int) -> tuple[PerformanceReview, User, PerformanceCycle]:
    r = ctx.db.get(PerformanceReview, rid)
    if r is None:
        raise NotFound("Review not found")
    subject = ctx.db.get(User, r.user_id)
    related = subject.id == ctx.user.id or r.reviewer_id == ctx.user.id or can_see_person(ctx, subject)
    if not related:
        raise NotFound("Review not found")
    return r, subject, ctx.db.get(PerformanceCycle, r.cycle_id)


def ser_review(ctx: Ctx, r: PerformanceReview, subject: User, cycle: PerformanceCycle, names: dict | None = None) -> dict:
    """The review as the caller may see it (see the module docstring)."""
    owner = subject.id == ctx.user.id
    shared = r.status in ("completed", "acknowledged")
    show_self = owner or r.self_submitted_at is not None
    show_mgr = (not owner) or shared
    ratings = r.ratings or {}

    def pick(side: str, bucket: str) -> dict:
        return {k: v.get(side) for k, v in (ratings.get(bucket) or {}).items() if v.get(side) is not None}

    names = names or {}
    out = {"id": r.id, "cycle_id": r.cycle_id, "cycle": cycle.name, "cycle_status": cycle.status, "user_id": subject.id, "employee": subject.full_name,
           "reviewer_id": r.reviewer_id, "reviewer": names.get(r.reviewer_id), "status": r.status,
           "self_due": cycle.self_review_due, "manager_due": cycle.manager_review_due,
           "self_rating": r.self_rating if show_self else None, "self_comments": r.self_comments if show_self else None, "self_submitted_at": r.self_submitted_at,
           "self_competencies": pick("self", "competencies") if show_self else {}, "self_goals": pick("self", "goals") if show_self else {},
           "manager_rating": r.manager_rating if show_mgr else None, "manager_comments": r.manager_comments if show_mgr else None,
           "strengths": r.strengths if show_mgr else None, "development_areas": r.development_areas if show_mgr else None,
           "manager_competencies": pick("manager", "competencies") if show_mgr else {}, "manager_goals": pick("manager", "goals") if show_mgr else {},
           "goal_score": r.goal_score if show_mgr else None, "manager_submitted_at": r.manager_submitted_at if show_mgr else None,
           "acknowledged_at": r.acknowledged_at, "employee_response": r.employee_response,
           "hidden_until_shared": owner and not shared and r.manager_submitted_at is None}
    return out


def _merge_ratings(r: PerformanceReview, side: str, competencies: dict[str, int], goals: dict[int, int], cycle: PerformanceCycle, allowed: list[int], db) -> None:
    known = set(cycle.competencies or [])
    for name, v in competencies.items():
        if name not in known:
            raise AppError(f"'{name}' is not part of this review form", status_code=422)
        check_rating(v, allowed, f"Rating for {name}")
    valid_goals = {g.id for g in db.scalars(select(Goal).where(Goal.cycle_id == cycle.id, Goal.user_id == r.user_id, Goal.status == "agreed"))}
    for gid, v in goals.items():
        if gid not in valid_goals:
            raise AppError("You can only rate agreed goals of this review", status_code=422)
        check_rating(v, allowed, "Goal rating")
    data = {"competencies": dict((r.ratings or {}).get("competencies") or {}), "goals": dict((r.ratings or {}).get("goals") or {})}
    for name, v in competencies.items():
        data["competencies"][name] = {**data["competencies"].get(name, {}), side: v}
    for gid, v in goals.items():
        data["goals"][str(gid)] = {**data["goals"].get(str(gid), {}), side: v}
    r.ratings = data


@router.get("/reviews/mine")
def my_reviews(cycle_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    q = select(PerformanceReview).where(PerformanceReview.user_id == ctx.user.id).order_by(PerformanceReview.id.desc())
    if cycle_id:
        q = q.where(PerformanceReview.cycle_id == cycle_id)
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    return {"items": [ser_review(ctx, r, ctx.user, ctx.db.get(PerformanceCycle, r.cycle_id), names) for r in ctx.db.scalars(q)]}


@router.get("/reviews")
def team_reviews(cycle_id: int, status: str | None = None, params: PageParams = Depends(), ctx: Ctx = Depends(require_roles("manager", "hr", "founder"))):
    """Reviews of the people you manage (founder: everyone in cycles; HR: their scope; manager: their team)."""
    cycle = ctx.db.get(PerformanceCycle, cycle_id)
    if cycle is None or (cycle.status == "draft" and not is_staff(ctx)):
        raise NotFound("Review cycle not found")
    stmt = select(PerformanceReview).join(User, User.id == PerformanceReview.user_id).where(PerformanceReview.cycle_id == cycle_id, PerformanceReview.user_id != ctx.user.id)
    if ctx.role == "manager":
        stmt = stmt.where(or_(PerformanceReview.reviewer_id == ctx.user.id, and_(User.manager_id == ctx.user.id)))
    elif ctx.role == "hr":
        stmt = stmt.where(user_scope(ctx))
    if status:
        stmt = stmt.where(PerformanceReview.status == status)
    stmt = stmt.order_by(User.full_name)
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    names = {i: u.full_name for i, u in users.items()}
    return paginate(ctx.db, stmt, params, lambda r: ser_review(ctx, r, users[r.user_id], cycle, names))


@router.get("/reviews/{rid}")
def get_review(rid: int, ctx: Ctx = Depends(get_ctx)):
    r, subject, cycle = _review(ctx, rid)
    if subject.id != ctx.user.id and r.reviewer_id != ctx.user.id:
        audit(ctx, "performance.review_viewed", "performance_review", r.id, {"user_id": subject.id})
        ctx.db.commit()
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    goals = [ser_goal(g) for g in ctx.db.scalars(select(Goal).where(Goal.cycle_id == cycle.id, Goal.user_id == subject.id, Goal.status == "agreed").order_by(Goal.id))]
    return {**ser_review(ctx, r, subject, cycle, names), "competencies": cycle.competencies or [], "scale": ser_scale(scale_for(ctx.db, cycle.scale_id)), "goals": goals,
            "can_review": can_review(ctx, r, subject) and r.status == "pending_manager" and cycle.status == "active"}


@router.put("/reviews/{rid}/self")
def save_self(rid: int, body: SelfIn, ctx: Ctx = Depends(get_ctx)):
    """Save (without submitting) your own part. Only you can see a draft."""
    r, subject, cycle = _review(ctx, rid)
    if subject.id != ctx.user.id:
        raise Forbidden("Only the person being reviewed writes the self review")
    if cycle.status != "active":
        raise Conflict("This review cycle is not open")
    if r.status != "pending_self":
        raise Conflict("Your self review was already submitted")
    allowed = allowed_values(ctx.db, cycle)
    check_rating(body.rating, allowed, "Rating")
    _merge_ratings(r, "self", body.competencies, body.goals, cycle, allowed, ctx.db)
    if body.rating is not None:
        r.self_rating = body.rating
    if body.comments is not None:
        r.self_comments = body.comments
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


@router.post("/reviews/{rid}/self/submit")
def submit_self(rid: int, ctx: Ctx = Depends(get_ctx)):
    r, subject, cycle = _review(ctx, rid)
    if subject.id != ctx.user.id:
        raise Forbidden("Only the person being reviewed submits the self review")
    if cycle.status != "active":
        raise Conflict("This review cycle is not open")
    if r.status != "pending_self":
        raise Conflict("Your self review was already submitted")
    missing = [n for n in (cycle.competencies or []) if ((r.ratings or {}).get("competencies", {}).get(n) or {}).get("self") is None]
    if r.self_rating is None or not (r.self_comments or "").strip() or missing:
        raise AppError("Give an overall rating, write your comments and rate every competency" + (f" (missing: {', '.join(missing)})" if missing else ""), code="incomplete")
    r.status, r.self_submitted_at = "pending_manager", utcnow()
    audit(ctx, "performance.self_review_submitted", "performance_review", r.id)
    who = [r.reviewer_id] if r.reviewer_id else [u.id for u in ctx.db.scalars(select(User).where(User.role.in_(("hr", "founder")), User.is_active.is_(True), User.id != subject.id)) if can_see_person(ctx_as(ctx, u), subject)]
    notify(ctx.db, who, "Self review submitted", f"{subject.full_name} submitted their self review for {cycle.name}", "performance", "/performance")
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


def ctx_as(ctx: Ctx, user: User) -> Ctx:
    return Ctx(user=user, db=ctx.db, company_id=ctx.company_id, company_slug=ctx.company_slug, ip=ctx.ip)


def _manager_guard(ctx: Ctx, rid: int) -> tuple[PerformanceReview, User, PerformanceCycle]:
    r, subject, cycle = _review(ctx, rid)
    if not can_review(ctx, r, subject):
        raise Forbidden("Only the person's reviewer can write the manager review")
    if cycle.status != "active":
        raise Conflict("This review cycle is not open")
    if r.status != "pending_manager":
        raise Conflict("The manager review opens after the self review is submitted" if r.status == "pending_self" else "The manager review was already submitted")
    return r, subject, cycle


@router.put("/reviews/{rid}/manager")
def save_manager(rid: int, body: ManagerIn, ctx: Ctx = Depends(get_ctx)):
    r, subject, cycle = _manager_guard(ctx, rid)
    allowed = allowed_values(ctx.db, cycle)
    check_rating(body.rating, allowed, "Rating")
    _merge_ratings(r, "manager", body.competencies, body.goals, cycle, allowed, ctx.db)
    for field, v in (("manager_rating", body.rating), ("manager_comments", body.comments), ("strengths", body.strengths), ("development_areas", body.development_areas)):
        if v is not None:
            setattr(r, field, v)
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


@router.post("/reviews/{rid}/manager/submit")
def submit_manager(rid: int, ctx: Ctx = Depends(get_ctx)):
    r, subject, cycle = _manager_guard(ctx, rid)
    missing = [n for n in (cycle.competencies or []) if ((r.ratings or {}).get("competencies", {}).get(n) or {}).get("manager") is None]
    if r.manager_rating is None or len((r.manager_comments or "").strip()) < 10 or missing:
        raise AppError("Give an overall rating, write comments (at least 10 characters) and rate every competency" + (f" (missing: {', '.join(missing)})" if missing else ""), code="incomplete")
    goals = {g.id: g for g in ctx.db.scalars(select(Goal).where(Goal.cycle_id == cycle.id, Goal.user_id == subject.id, Goal.status == "agreed"))}
    items = [(goals[int(gid)].weight, v.get("manager")) for gid, v in ((r.ratings or {}).get("goals") or {}).items() if int(gid) in goals]
    r.goal_score = rules.weighted_score(items)
    r.status, r.manager_submitted_at, r.manager_submitted_by = "completed", utcnow(), ctx.user.id
    audit(ctx, "performance.manager_review_submitted", "performance_review", r.id)
    notify(ctx.db, [subject.id], "Your performance review is ready", f"{cycle.name}: read your manager's review and acknowledge it", "performance", "/performance")
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


@router.post("/reviews/{rid}/acknowledge")
def acknowledge(rid: int, body: AckIn, ctx: Ctx = Depends(get_ctx)):
    r, subject, cycle = _review(ctx, rid)
    if subject.id != ctx.user.id:
        raise Forbidden("Only the person reviewed can acknowledge it")
    if r.status != "completed":
        raise Conflict("There is nothing to acknowledge yet" if r.status != "acknowledged" else "Already acknowledged")
    r.status, r.acknowledged_at, r.employee_response = "acknowledged", utcnow(), (body.response or "").strip() or None
    audit(ctx, "performance.review_acknowledged", "performance_review", r.id)
    notify(ctx.db, [x for x in (r.manager_submitted_by, r.reviewer_id) if x], "Review acknowledged", f"{subject.full_name} acknowledged the {cycle.name} review", "performance", "/performance")
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


@router.post("/reviews/{rid}/reassign")
def reassign(rid: int, body: ReassignIn, ctx: Ctx = Depends(staff)):
    """HR / founder: name a different reviewer (the manager left, changed team, or there was none)."""
    r, subject, cycle = _review(ctx, rid)
    if cycle.status != "active" or r.status not in ("pending_self", "pending_manager"):
        raise Conflict("This review can no longer change reviewer")
    new = ctx.db.get(User, body.reviewer_id)
    if new is None or not new.is_active or new.id == subject.id or new.role not in ("manager", "hr", "founder"):
        raise AppError("Choose an active manager, HR or founder other than the person being reviewed")
    r.reviewer_id = new.id
    audit(ctx, "performance.reviewer_changed", "performance_review", r.id, {"reviewer_id": new.id})
    notify(ctx.db, [new.id], "You were asked to review", f"{subject.full_name} ({cycle.name})", "performance", "/performance")
    ctx.db.commit()
    return ser_review(ctx, r, subject, cycle)


@router.get("/history/{user_id}")
def history(user_id: int, ctx: Ctx = Depends(get_ctx)):
    """A person's past appraisals, newest first. Yourself (only what has been shared with you), or someone in your scope."""
    u = person(ctx, user_id)
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    q = select(PerformanceReview).where(PerformanceReview.user_id == u.id).order_by(PerformanceReview.id.desc())
    out = []
    for r in ctx.db.scalars(q):
        cycle = ctx.db.get(PerformanceCycle, r.cycle_id)
        if cycle.status == "draft":
            continue
        out.append(ser_review(ctx, r, u, cycle, names))
    if u.id != ctx.user.id:
        audit(ctx, "performance.history_viewed", "user", u.id)
        ctx.db.commit()
    return {"user": {"id": u.id, "name": u.full_name}, "items": out}


# ================================================================== feedback

class FeedbackIn(BaseModel):
    to_user_id: int
    body: str = Field(min_length=3, max_length=2000)
    kind: Literal["praise", "constructive"] = "praise"
    shared: bool = True
    cycle_id: int | None = None


def ser_feedback(f: Feedback, names: dict, anonymise_giver: bool = False) -> dict:
    return {"id": f.id, "from_user_id": f.from_user_id, "from": names.get(f.from_user_id), "to_user_id": f.to_user_id, "to": names.get(f.to_user_id), "kind": f.kind,
            "body": f.body, "shared": f.shared, "cycle_id": f.cycle_id, "created_at": f.created_at}


@router.post("/feedback", status_code=201)
def give_feedback(body: FeedbackIn, ctx: Ctx = Depends(get_ctx)):
    if ctx.role in ("board_member",):
        raise Forbidden()
    to = ctx.db.get(User, body.to_user_id)
    if to is None or not to.is_active or to.role not in REVIEWED or to.id == ctx.user.id:
        raise AppError("Choose a colleague to give feedback to")
    f = Feedback(from_user_id=ctx.user.id, to_user_id=to.id, kind=body.kind, body=body.body.strip(), shared=body.shared, cycle_id=body.cycle_id)
    ctx.db.add(f)
    ctx.db.flush()
    audit(ctx, "performance.feedback_given", "feedback", f.id, {"to": to.id})
    if body.shared:
        notify(ctx.db, [to.id], "You received feedback", f"{ctx.user.full_name} shared feedback with you", "performance", "/performance")
    ctx.db.commit()
    return ser_feedback(f, {ctx.user.id: ctx.user.full_name, to.id: to.full_name})


@router.get("/feedback/received")
def feedback_received(params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Feedback).where(Feedback.to_user_id == ctx.user.id, Feedback.shared.is_(True)).order_by(Feedback.id.desc())
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    return paginate(ctx.db, stmt, params, lambda f: ser_feedback(f, names))


@router.get("/feedback/given")
def feedback_given(params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Feedback).where(Feedback.from_user_id == ctx.user.id).order_by(Feedback.id.desc())
    names = {u.id: u.full_name for u in ctx.db.scalars(select(User))}
    return paginate(ctx.db, stmt, params, lambda f: ser_feedback(f, names))


@router.get("/feedback/about/{user_id}")
def feedback_about(user_id: int, params: PageParams = Depends(), ctx: Ctx = Depends(require_roles("manager", "hr", "founder"))):
    """Everything said about someone you manage, including feedback the giver chose not to share with them."""
    u = person(ctx, user_id)
    if u.id == ctx.user.id:
        raise NotFound("Person not found")
    stmt = select(Feedback).where(Feedback.to_user_id == u.id).order_by(Feedback.id.desc())
    names = {x.id: x.full_name for x in ctx.db.scalars(select(User))}
    audit(ctx, "performance.feedback_viewed", "user", u.id)
    ctx.db.commit()
    return paginate(ctx.db, stmt, params, lambda f: ser_feedback(f, names))


# ================================================================== reports

def _scoped_reviews(ctx: Ctx, cycle_id: int):
    stmt = select(PerformanceReview).join(User, User.id == PerformanceReview.user_id).where(PerformanceReview.cycle_id == cycle_id)
    if ctx.role == "hr":
        stmt = stmt.where(user_scope(ctx))
    elif ctx.role == "manager":
        stmt = stmt.where(or_(PerformanceReview.reviewer_id == ctx.user.id, User.manager_id == ctx.user.id), PerformanceReview.user_id != ctx.user.id)
    return stmt


@router.get("/cycles/{cid}/summary")
def cycle_summary(cid: int, ctx: Ctx = Depends(require_roles("manager", "hr", "founder"))):
    """Completion, rating distribution and averages for the people you manage. Ratings count only once the manager has submitted."""
    cycle = ctx.db.get(PerformanceCycle, cid)
    if cycle is None or (cycle.status == "draft" and not is_staff(ctx)):
        raise NotFound("Review cycle not found")
    values = allowed_values(ctx.db, cycle)
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    depts = {d.id: d.name for d in ctx.db.scalars(select(Department))}
    rows = list(ctx.db.scalars(_scoped_reviews(ctx, cid)))
    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    done = [r for r in rows if r.manager_submitted_at is not None]
    today = utcnow().date()
    overdue_self = sum(1 for r in rows if r.status == "pending_self" and cycle.self_review_due and today > cycle.self_review_due)
    overdue_mgr = sum(1 for r in rows if r.status == "pending_manager" and cycle.manager_review_due and today > cycle.manager_review_due)
    by_dept: dict[str, list[int]] = {}
    for r in done:
        by_dept.setdefault(depts.get(users[r.user_id].department_id, "No department"), []).append(r.manager_rating)
    goals = list(ctx.db.scalars(select(Goal).join(User, User.id == Goal.user_id).where(Goal.cycle_id == cid, Goal.status == "agreed",
                                                                                  Goal.user_id.in_(select(PerformanceReview.user_id).where(PerformanceReview.cycle_id == cid)),
                                                                                  *( [user_scope(ctx)] if ctx.role == "hr" else []))))
    if ctx.role == "manager":
        mine = {r.user_id for r in rows}
        goals = [g for g in goals if g.user_id in mine]
    return {"cycle": {"id": cycle.id, "name": cycle.name, "status": cycle.status}, "participants": len(rows), "statuses": status_counts,
            "completion": {"self_submitted": sum(1 for r in rows if r.self_submitted_at), "manager_submitted": len(done), "acknowledged": status_counts.get("acknowledged", 0)},
            "overdue": {"self": overdue_self, "manager": overdue_mgr},
            "average_self": rules.average([r.self_rating for r in rows if r.self_rating is not None and r.self_submitted_at]),
            "average_manager": rules.average([r.manager_rating for r in done]),
            "distribution": [{"value": v, "label": next(lv.label for lv in scale_for(ctx.db, cycle.scale_id).levels if lv.value == v), "count": c}
                             for v, c in rules.distribution([r.manager_rating for r in done], values).items()],
            "by_department": [{"department": k, "reviews": len(v), "average": rules.average(v)} for k, v in sorted(by_dept.items())],
            "goals": {"count": len(goals), "average_progress": rules.average([g.progress for g in goals]), "completed": sum(1 for g in goals if g.progress >= 100)}}


@router.get("/cycles/{cid}/export.csv")
def export_cycle(cid: int, ctx: Ctx = Depends(staff)):
    cycle = ctx.db.get(PerformanceCycle, cid)
    if cycle is None:
        raise NotFound("Review cycle not found")
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    depts = {d.id: d.name for d in ctx.db.scalars(select(Department))}
    rows = []
    for r in ctx.db.scalars(_scoped_reviews(ctx, cid).order_by(User.full_name)):
        u = users[r.user_id]
        rows.append([u.employee_code or "", u.full_name, depts.get(u.department_id, ""), users[r.reviewer_id].full_name if r.reviewer_id in users else "", r.status,
                     r.self_rating if r.self_submitted_at else "", r.manager_rating if r.manager_submitted_at else "", r.goal_score if r.manager_submitted_at else "",
                     "yes" if r.acknowledged_at else ""])
    audit(ctx, "performance.cycle_exported", "performance_cycle", cid, {"rows": len(rows)})
    ctx.db.commit()
    body = to_csv(["Employee code", "Employee", "Department", "Reviewer", "Status", "Self rating", "Manager rating", "Goal score", "Acknowledged"], rows)
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="performance-{cid}.csv"'})
