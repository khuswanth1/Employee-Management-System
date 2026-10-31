"""Shift definitions, who works which shift, and the optional per-branch geo-fence."""
from datetime import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import func, select

from app.access import user_scope
from app.common import audit
from app.core.errors import AppError, Conflict, NotFound
from app.db.tenant_models import Attendance, Branch, Shift, User
from app.deps import Ctx, get_ctx, require_roles

router = APIRouter(prefix="/attendance", tags=["attendance setup"])
staff = require_roles("founder", "hr")
viewers = require_roles("founder", "hr", "manager")


class ShiftIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    start_time: time | None = None
    end_time: time | None = None
    grace_minutes: int = Field(0, ge=0, le=120)
    required_hours: float = Field(8.0, ge=1, le=16)
    half_day_hours: float | None = Field(None, gt=0, le=16)
    overtime_after_hours: float | None = Field(None, gt=0, le=24)
    is_active: bool = True

    @model_validator(mode="after")
    def _consistent(self):
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Give both a start and an end time, or neither for a flexible shift")
        if self.start_time is not None and self.start_time == self.end_time:
            raise ValueError("Start and end time cannot be the same")
        if self.half_day_hours is not None and self.half_day_hours > self.required_hours:
            raise ValueError("Half-day hours cannot exceed the required hours")
        return self


class ShiftPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    start_time: time | None = None
    end_time: time | None = None
    grace_minutes: int | None = Field(None, ge=0, le=120)
    required_hours: float | None = Field(None, ge=1, le=16)
    half_day_hours: float | None = Field(None, gt=0, le=16)
    overtime_after_hours: float | None = Field(None, gt=0, le=24)
    is_active: bool | None = None


class AssignIn(BaseModel):
    shift_id: int | None = None  # None = remove the assignment
    user_ids: list[int] = Field(min_length=1, max_length=500)


class GeofenceIn(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    radius_m: int | None = Field(None, ge=20, le=50_000)
    required: bool = False

    @model_validator(mode="after")
    def _complete(self):
        if self.required and (self.lat is None or self.lng is None or not self.radius_m):
            raise ValueError("A required geo-fence needs a latitude, longitude and radius")
        return self


def ser(s: Shift, assigned: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "start_time": s.start_time, "end_time": s.end_time, "flexible": s.start_time is None,
            "overnight": s.start_time is not None and s.end_time <= s.start_time, "grace_minutes": s.grace_minutes,
            "required_hours": s.required_hours, "half_day_hours": s.half_day_hours, "overtime_after_hours": s.overtime_after_hours,
            "is_active": s.is_active, "assigned": assigned}


def _get(ctx: Ctx, sid: int) -> Shift:
    s = ctx.db.get(Shift, sid)
    if s is None:
        raise NotFound("Shift not found")
    return s


@router.get("/shifts")
def list_shifts(ctx: Ctx = Depends(viewers)):
    counts = dict(ctx.db.execute(select(User.shift_id, func.count(User.id)).where(User.shift_id.is_not(None)).group_by(User.shift_id)).all())
    return {"items": [ser(s, counts.get(s.id, 0)) for s in ctx.db.scalars(select(Shift).order_by(Shift.name))]}


@router.post("/shifts", status_code=201)
def create_shift(body: ShiftIn, ctx: Ctx = Depends(staff)):
    if ctx.db.scalar(select(Shift.id).where(func.lower(Shift.name) == body.name.lower())):
        raise Conflict("A shift with this name already exists")
    s = Shift(**body.model_dump())
    ctx.db.add(s)
    ctx.db.flush()
    audit(ctx, "attendance.shift_created", "shift", s.id)
    ctx.db.commit()
    return ser(s)


@router.patch("/shifts/{sid}")
def update_shift(sid: int, body: ShiftPatch, ctx: Ctx = Depends(staff)):
    s = _get(ctx, sid)
    data = body.model_dump(exclude_unset=True)
    merged = {**ser(s), **{k: v for k, v in data.items()}}
    try:  # the merged result must still be a valid shift
        ShiftIn(name=merged["name"], start_time=merged["start_time"], end_time=merged["end_time"], grace_minutes=merged["grace_minutes"],
                required_hours=merged["required_hours"], half_day_hours=merged["half_day_hours"], overtime_after_hours=merged["overtime_after_hours"])
    except ValidationError as e:
        raise AppError(e.errors()[0]["msg"].removeprefix("Value error, "), status_code=422, code="validation_error") from None
    if "name" in data and ctx.db.scalar(select(Shift.id).where(func.lower(Shift.name) == data["name"].lower(), Shift.id != sid)):
        raise Conflict("A shift with this name already exists")
    for k, v in data.items():
        setattr(s, k, v)
    audit(ctx, "attendance.shift_updated", "shift", s.id, {"fields": sorted(data)})  # past records keep their frozen numbers
    ctx.db.commit()
    return ser(s)


@router.delete("/shifts/{sid}", status_code=204)
def delete_shift(sid: int, ctx: Ctx = Depends(staff)):
    s = _get(ctx, sid)
    if ctx.db.scalar(select(User.id).where(User.shift_id == sid)) or ctx.db.scalar(select(Attendance.id).where(Attendance.shift_id == sid)):
        raise Conflict("This shift is assigned or has attendance history; deactivate it instead")
    ctx.db.delete(s)
    audit(ctx, "attendance.shift_deleted", "shift", sid)
    ctx.db.commit()


@router.post("/shift-assignments")
def assign(body: AssignIn, ctx: Ctx = Depends(staff)):
    """Applies to FUTURE check-ins; sessions already recorded keep the shift they were worked under."""
    if body.shift_id is not None:
        s = _get(ctx, body.shift_id)
        if not s.is_active:
            raise AppError("This shift is inactive")
    users = list(ctx.db.scalars(select(User).where(User.id.in_(body.user_ids), User.is_active.is_(True), user_scope(ctx))))
    if len(users) != len(set(body.user_ids)):
        raise NotFound("Some people were not found in your scope")
    for u in users:
        u.shift_id = body.shift_id
    audit(ctx, "attendance.shift_assigned", "shift", body.shift_id, {"user_ids": sorted(u.id for u in users)})
    ctx.db.commit()
    return {"updated": len(users)}


@router.get("/geofences")
def geofences(ctx: Ctx = Depends(viewers)):
    return {"items": [{"branch_id": b.id, "branch": b.name, "lat": b.geo_lat, "lng": b.geo_lng, "radius_m": b.geo_radius_m, "required": b.geo_required}
                      for b in ctx.db.scalars(select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name))]}


@router.put("/geofences/{branch_id}")
def set_geofence(branch_id: int, body: GeofenceIn, ctx: Ctx = Depends(staff)):
    b = ctx.db.get(Branch, branch_id)
    if b is None or (ctx.role == "hr" and ctx.user.branch_id is not None and ctx.user.branch_id != b.id):
        raise NotFound("Branch not found")
    b.geo_lat, b.geo_lng, b.geo_radius_m, b.geo_required = body.lat, body.lng, body.radius_m, body.required
    audit(ctx, "attendance.geofence_set", "branch", b.id, {"required": body.required, "radius_m": body.radius_m})
    ctx.db.commit()
    return {"branch_id": b.id, "lat": b.geo_lat, "lng": b.geo_lng, "radius_m": b.geo_radius_m, "required": b.geo_required}
