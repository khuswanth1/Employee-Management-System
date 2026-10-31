"""Employment history. `record` is the only writer: events are appended, never changed."""
from datetime import date

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.tenant_models import EmployeeEvent

KINDS = ("joined", "activated", "probation_set", "confirmed", "promoted", "role_changed", "department_changed", "branch_changed", "manager_changed",
         "suspended", "reinstated", "resignation_submitted", "resignation_withdrawn", "offboarded", "exit_cleared", "reactivated")
# Seen only by the people who administer the account. Everything else is also visible to the person and to their line manager.
INTERNAL = frozenset({"suspended", "reinstated", "exit_cleared"})


def record(db: Session, user_id: int, kind: str, *, actor_id: int | None, effective: date | None = None, frm: dict | None = None,
           to: dict | None = None, note: str | None = None) -> EmployeeEvent:
    assert kind in KINDS, kind
    e = EmployeeEvent(user_id=user_id, kind=kind, effective_date=effective or utcnow().date(), from_value=frm, to_value=to, note=note, created_by=actor_id)
    db.add(e)
    return e
