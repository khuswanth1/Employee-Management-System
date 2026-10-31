from datetime import date

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.core.security import hash_password
from app.db.tenant_models import LeaveType, Setting, User
from app.modules.employees.events import record
from app.modules.leave.service import ensure_balances

DEFAULT_LEAVE_TYPES = [("Annual Leave", 18, True), ("Sick Leave", 10, True), ("Casual Leave", 6, True), ("Unpaid Leave", 0, False)]
DEFAULT_SETTINGS = {"standard_work_hours": "8", "company_timezone": "UTC"}


def seed_tenant(db: Session, *, founder_email: str, founder_name: str, founder_password: str) -> User:
    for name, quota, paid in DEFAULT_LEAVE_TYPES:
        db.add(LeaveType(name=name, annual_quota=quota, paid=paid))
    for k, v in DEFAULT_SETTINGS.items():
        db.add(Setting(key=k, value=v))
    founder = User(
        email=founder_email.lower(),
        full_name=founder_name,
        password_hash=hash_password(founder_password),
        role="founder",
        status="active",
        hire_date=utcnow().date(),
        designation="Founder",
    )
    db.add(founder)
    db.flush()
    ensure_balances(db, founder, utcnow().date().year)
    record(db, founder.id, "joined", actor_id=None, effective=founder.hire_date, to={"designation": "Founder", "role": "founder"})
    db.commit()
    return founder
