"""Shared helpers: pagination, audit log, CSV safety."""
import csv
import io
from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.tenant_models import AuditLog, Setting


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class PageParams:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        self.page = page
        self.page_size = page_size


def paginate(db: Session, stmt: Select, params: PageParams, serializer) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(params.page_size).offset((params.page - 1) * params.page_size)).all()
    return {"items": [serializer(r) for r in rows], "total": total, "page": params.page, "page_size": params.page_size}


def audit(ctx, action: str, entity_type: str | None = None, entity_id: int | None = None, detail: dict | None = None) -> None:
    ctx.db.add(AuditLog(actor_id=ctx.user.id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail, ip=ctx.ip))


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_csv(headers: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([csv_safe(c) for c in r])
    return buf.getvalue()
