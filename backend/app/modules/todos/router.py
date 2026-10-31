"""Personal task manager: main tasks with subtasks, priority, estimated duration, status and manual ordering.

Everything is private to the signed-in user (every query filters on user_id). Subtasks are one level deep.
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.errors import AppError, NotFound
from app.db.tenant_models import Todo
from app.deps import Ctx, get_ctx

router = APIRouter(prefix="/todos", tags=["todos"])

Priority = Literal["high", "medium", "low"]
Status = Literal["todo", "in_progress", "completed"]
MAX_TASKS = 500             # main tasks per person
MAX_SUBTASKS = 50           # subtasks per main task
MAX_MINUTES = 60 * 24 * 30  # one month of effort is the largest estimate accepted


def _clean_title(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Title is required")
    return v


class TodoIn(BaseModel):
    title: str = Field(max_length=200)
    notes: str | None = Field(None, max_length=2000)
    priority: Priority = "medium"
    status: Status = "todo"
    duration_minutes: int | None = Field(None, ge=0, le=MAX_MINUTES)
    parent_id: int | None = None

    _t = field_validator("title")(classmethod(lambda cls, v: _clean_title(v)))


class TodoPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    priority: Priority | None = None
    status: Status | None = None
    duration_minutes: int | None = Field(None, ge=0, le=MAX_MINUTES)

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return None if v is None else _clean_title(v)


class MoveIn(BaseModel):
    parent_id: int | None = None  # null = top level
    index: int = Field(ge=0, le=100000)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mine(ctx: Ctx, tid: int) -> Todo:
    t = ctx.db.scalar(select(Todo).where(Todo.id == tid, Todo.user_id == ctx.user.id))
    if t is None:
        raise NotFound("Task not found")
    return t


def _siblings(ctx: Ctx, parent_id: int | None) -> list[Todo]:
    cond = Todo.parent_id.is_(None) if parent_id is None else Todo.parent_id == parent_id
    return list(ctx.db.scalars(select(Todo).where(Todo.user_id == ctx.user.id, cond).order_by(Todo.position, Todo.id)))


def _renumber(rows: list[Todo]) -> None:
    for i, r in enumerate(rows):
        if r.position != i:
            r.position = i


def _set_status(t: Todo, status: str) -> None:
    t.status = status
    t.completed_at = _now() if status == "completed" else None


def _minutes(t: Todo) -> int:
    return t.duration_minutes or 0


def _ser(t: Todo, subs: list[Todo] | None = None) -> dict:
    out = {
        "id": t.id, "parent_id": t.parent_id, "title": t.title, "notes": t.notes, "priority": t.priority, "status": t.status,
        "duration_minutes": t.duration_minutes, "position": t.position,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }
    if subs is not None:
        out["subtasks"] = [_ser(s) for s in subs]
        out["subtasks_done"] = sum(1 for s in subs if s.status == "completed")
        out["subtask_count"] = len(subs)
        # time needed: this task's own estimate plus every subtask's; "remaining" leaves out what is already completed
        out["total_minutes"] = _minutes(t) + sum(_minutes(s) for s in subs)
        out["remaining_minutes"] = (0 if t.status == "completed" else _minutes(t)) + sum(_minutes(s) for s in subs if s.status != "completed")
    return out


def _tree(ctx: Ctx) -> list[dict]:
    rows = list(ctx.db.scalars(select(Todo).where(Todo.user_id == ctx.user.id).order_by(Todo.position, Todo.id)))
    subs: dict[int, list[Todo]] = {}
    for r in rows:
        if r.parent_id is not None:
            subs.setdefault(r.parent_id, []).append(r)
    return [_ser(r, subs.get(r.id, [])) for r in rows if r.parent_id is None]


def _summary(items: list[dict]) -> dict:
    s = {"total": len(items), "todo": 0, "in_progress": 0, "completed": 0, "remaining_minutes": 0, "total_minutes": 0}
    for i in items:
        s[i["status"]] += 1
        s["remaining_minutes"] += i["remaining_minutes"]
        s["total_minutes"] += i["total_minutes"]
    return s


def _sync_parent(ctx: Ctx, parent: Todo, changed: Todo | None = None) -> None:
    """Keep a main task consistent with its subtasks: all done -> completed; a reopened subtask reopens a completed parent;
    work started on a subtask starts a waiting parent."""
    subs = _siblings(ctx, parent.id)
    if subs and all(s.status == "completed" for s in subs):
        if parent.status != "completed":
            _set_status(parent, "completed")
        return
    if parent.status == "completed" and any(s.status != "completed" for s in subs):
        _set_status(parent, "in_progress")
    if changed is not None and changed.status == "in_progress" and parent.status == "todo":
        _set_status(parent, "in_progress")


@router.get("")
def list_todos(ctx: Ctx = Depends(get_ctx)):
    items = _tree(ctx)
    return {"items": items, "summary": _summary(items)}


@router.post("", status_code=201)
def create_todo(body: TodoIn, ctx: Ctx = Depends(get_ctx)):
    parent = None
    if body.parent_id is not None:
        parent = _mine(ctx, body.parent_id)
        if parent.parent_id is not None:
            raise AppError("A subtask cannot have subtasks of its own")
    siblings = _siblings(ctx, body.parent_id)
    if parent is None and len(siblings) >= MAX_TASKS:
        raise AppError(f"You can keep up to {MAX_TASKS} tasks. Delete finished ones first.")
    if parent is not None and len(siblings) >= MAX_SUBTASKS:
        raise AppError(f"A task can have up to {MAX_SUBTASKS} subtasks")
    t = Todo(user_id=ctx.user.id, parent_id=body.parent_id, title=body.title, notes=(body.notes or "").strip() or None,
             priority=body.priority, duration_minutes=body.duration_minutes, position=len(siblings))
    _set_status(t, body.status)
    ctx.db.add(t)
    ctx.db.flush()
    if parent is not None:
        _sync_parent(ctx, parent, t)
    ctx.db.commit()
    return _ser(t, [] if parent is None else None)


@router.patch("/{tid}")
def update_todo(tid: int, body: TodoPatch, ctx: Ctx = Depends(get_ctx)):
    t = _mine(ctx, tid)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is None:
        raise AppError("Title is required")
    for k in ("priority", "status"):
        if k in data and data[k] is None:
            raise AppError(f"{k.title()} cannot be empty")
    if "notes" in data:
        t.notes = (data["notes"] or "").strip() or None
    for k in ("title", "priority", "duration_minutes"):
        if k in data:
            setattr(t, k, data[k])
    if "status" in data and data["status"] != t.status:
        _set_status(t, data["status"])
        if t.parent_id is None and t.status == "completed":  # finishing a main task finishes its subtasks
            for s in _siblings(ctx, t.id):
                if s.status != "completed":
                    _set_status(s, "completed")
        if t.parent_id is not None:
            _sync_parent(ctx, _mine(ctx, t.parent_id), t)
    ctx.db.commit()
    return _ser(t, _siblings(ctx, t.id) if t.parent_id is None else None)


@router.delete("/{tid}", status_code=204)
def delete_todo(tid: int, ctx: Ctx = Depends(get_ctx)):
    t = _mine(ctx, tid)
    parent_id = t.parent_id
    for s in _siblings(ctx, t.id):
        ctx.db.delete(s)
    ctx.db.delete(t)
    ctx.db.flush()
    _renumber(_siblings(ctx, parent_id))
    if parent_id is not None:
        _sync_parent(ctx, _mine(ctx, parent_id))
    ctx.db.commit()


@router.post("/{tid}/move")
def move_todo(tid: int, body: MoveIn, ctx: Ctx = Depends(get_ctx)):
    """Drag and drop: put a task at `index` under `parent_id` (null = top level). Also moves a subtask to another task."""
    t = _mine(ctx, tid)
    old_parent = t.parent_id
    if body.parent_id is not None:
        if body.parent_id == t.id:
            raise AppError("A task cannot be its own subtask")
        new_parent = _mine(ctx, body.parent_id)
        if new_parent.parent_id is not None:
            raise AppError("Subtasks cannot have subtasks of their own")
        if _siblings(ctx, t.id):
            raise AppError("A task that has subtasks cannot become a subtask. Move or delete its subtasks first.")
        if old_parent != body.parent_id and len(_siblings(ctx, body.parent_id)) >= MAX_SUBTASKS:
            raise AppError(f"A task can have up to {MAX_SUBTASKS} subtasks")
    dest = [s for s in _siblings(ctx, body.parent_id) if s.id != t.id]
    dest.insert(min(body.index, len(dest)), t)
    t.parent_id = body.parent_id
    _renumber(dest)
    ctx.db.flush()
    if old_parent != body.parent_id:
        _renumber(_siblings(ctx, old_parent))
    for pid in {p for p in (old_parent, body.parent_id) if p is not None}:
        _sync_parent(ctx, _mine(ctx, pid), t if pid == body.parent_id else None)
    ctx.db.commit()
    items = _tree(ctx)
    return {"items": items, "summary": _summary(items)}
