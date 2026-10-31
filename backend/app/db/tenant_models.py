from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TenantBase, utcnow

ROLES = ("founder", "hr", "manager", "employee", "board_member")


class Department(TenantBase):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    head_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    cost_center: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")  # active|inactive


class Branch(TenantBase):
    """A company branch / office location. Users are assigned to at most one branch."""

    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    timezone: Mapped[str | None] = mapped_column(String(64))
    working_days: Mapped[list | None] = mapped_column(JSON)  # ["mon", ...]; None = company default
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    hr_representative_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # optional geo-fence for office check-ins (work-from-home check-ins are exempt)
    geo_lat: Mapped[float | None] = mapped_column(Float)
    geo_lng: Mapped[float | None] = mapped_column(Float)
    geo_radius_m: Mapped[int | None] = mapped_column(Integer)
    geo_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class User(TenantBase):
    """An employee account. Every person in a tenant is a row here."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="onboarding")  # onboarding|active|offboarded
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    designation: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    avatar_name: Mapped[str | None] = mapped_column(String(32))  # stored file name of the profile photo
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last time a live connection of this person opened or closed
    employee_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))
    location: Mapped[str | None] = mapped_column(String(120))  # work location; defaults to the branch's city
    permissions: Mapped[list | None] = mapped_column(JSON)  # explicit permission keys (managers); None = role defaults
    hire_date: Mapped[date | None] = mapped_column(Date)
    offboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # bump to sign out every session
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(255))  # Fernet-encrypted TOTP secret; set while enrolling too
    mfa_last_step: Mapped[int | None] = mapped_column(Integer)  # last accepted TOTP time step (replay guard)
    mfa_recovery: Mapped[list | None] = mapped_column(JSON)  # sha256 hashes of unused recovery codes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    department: Mapped[Department | None] = relationship(foreign_keys=[department_id])

    __table_args__ = (Index("ix_users_manager", "manager_id"), Index("ix_users_department", "department_id"), Index("ix_users_branch", "branch_id"))


class AuthToken(TenantBase):
    """Single-use e-mailed links (password reset, e-mail verification). Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # reset | verify
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmployeeDocument(TenantBase):
    __tablename__ = "employee_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(60), default="other")
    stored_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")  # pending|verified|rejected
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmployeeProfile(TenantBase):
    """Extended HR record, one row per person. Kept apart from `users` so restricted personal data
    (personal email, birth date, address, emergency contact) has its own access rule and audit trail."""

    __tablename__ = "employee_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(String(100))
    employment_type: Mapped[str | None] = mapped_column(String(20))
    employment_category: Mapped[str | None] = mapped_column(String(60))
    job_level: Mapped[str | None] = mapped_column(String(40))
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    last_working_date: Mapped[date | None] = mapped_column(Date)
    skills: Mapped[list | None] = mapped_column(JSON)
    certifications: Mapped[list | None] = mapped_column(JSON)
    tags: Mapped[list | None] = mapped_column(JSON)
    # restricted: visible to the person themself and to HR/founders who administer the account
    personal_email: Mapped[str | None] = mapped_column(String(255))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(300))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120))
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(60))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(40))
    emergency_contact_address: Mapped[str | None] = mapped_column(String(300))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChecklistItem(TenantBase):
    """Onboarding / offboarding checklist entries."""

    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # onboarding | offboarding
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Project(TenantBase):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    category: Mapped[str | None] = mapped_column(String(60))
    client_name: Mapped[str | None] = mapped_column(String(120))
    risk_level: Mapped[str] = mapped_column(String(10), default="low", server_default="low")  # low|medium|high|critical
    visibility: Mapped[str] = mapped_column(String(12), default="restricted", server_default="restricted")  # restricted|company
    estimated_hours: Mapped[float | None] = mapped_column(Float)
    tags: Mapped[list | None] = mapped_column(JSON)
    completed_on: Mapped[date | None] = mapped_column(Date)

    members: Mapped[list["ProjectMember"]] = relationship(cascade="all, delete-orphan")


class ProjectMember(TenantBase):
    __tablename__ = "project_members"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Milestone(TenantBase):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(TenantBase):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("milestones.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo|in_progress|review|done
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    due_date: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    blocker_note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    task_type: Mapped[str] = mapped_column(String(20), default="feature", server_default="feature")
    labels: Mapped[list | None] = mapped_column(JSON)
    start_date: Mapped[date | None] = mapped_column(Date)
    estimated_hours: Mapped[float | None] = mapped_column(Float)
    actual_hours: Mapped[float | None] = mapped_column(Float)
    review_notes: Mapped[str | None] = mapped_column(Text)
    completed_on: Mapped[date | None] = mapped_column(Date)


class TaskDependency(TenantBase):
    __tablename__ = "task_dependencies"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)


class Attachment(TenantBase):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))  # task | project
    entity_id: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_attachments_entity", "entity_type", "entity_id"),)


class TaskComment(TenantBase):
    """A discussion entry on a project task. Deleted with the task; the author link is cleared (not the text) if the account is ever removed."""

    __tablename__ = "task_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyUpdate(TenantBase):
    __tablename__ = "daily_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    completed: Mapped[str] = mapped_column(Text, default="")
    hours_worked: Mapped[float] = mapped_column(Float, default=0)
    pending: Mapped[str | None] = mapped_column(Text)
    blockers: Mapped[str | None] = mapped_column(Text)
    next_plan: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|reviewed|needs_changes
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "work_date", name="uq_daily_update_user_date"),)


class LeaveType(TenantBase):
    __tablename__ = "leave_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    annual_quota: Mapped[float] = mapped_column(Float, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- policy (changing these never rewrites leave that was already approved; see modules/leave/service.py)
    accrual: Mapped[str] = mapped_column(String(16), default="annual_upfront", server_default="annual_upfront")  # annual_upfront | monthly
    carry_forward_max: Mapped[float] = mapped_column(Float, default=0, server_default="0")  # days that may move into next year
    carry_expiry_months: Mapped[int | None] = mapped_column(Integer)  # carried days lapse at the end of this month of the new year
    allow_half_day: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    count_all_days: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # True: weekends/holidays inside the range count too
    min_notice_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_consecutive_days: Mapped[float | None] = mapped_column(Float)
    encashable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    encash_max_days: Mapped[float | None] = mapped_column(Float)  # per year
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class LeaveBalance(TenantBase):
    __tablename__ = "leave_balances"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer)
    allocated: Mapped[float] = mapped_column(Float, default=0)  # granted this year (annual or accrued) plus adjustments
    used: Mapped[float] = mapped_column(Float, default=0)
    carried_in: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    expired: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    encashed: Mapped[float] = mapped_column(Float, default=0, server_default="0")

    @property
    def remaining(self) -> float:
        return round(self.allocated + self.carried_in - self.used - self.expired - self.encashed, 4)

    __table_args__ = (UniqueConstraint("user_id", "leave_type_id", "year", name="uq_leave_balance"),)


class LeaveLedger(TenantBase):
    """Append-only history of every change to a balance. `days` is the effect on the remaining balance. (request_id, kind) and
    (user, type, year, kind, period) are unique, so a retried approval, cancellation or accrual can never be booked twice."""

    __tablename__ = "leave_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))  # grant | carry_in | adjust | use | refund | expire | encash
    days: Mapped[float] = mapped_column(Float)
    period: Mapped[str | None] = mapped_column(String(24))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("leave_requests.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("request_id", "kind", name="uq_leave_ledger_request_kind"),
        UniqueConstraint("user_id", "leave_type_id", "year", "kind", "period", name="uq_leave_ledger_period"),
        Index("ix_leave_ledger_balance", "user_id", "leave_type_id", "year"),
    )


class LeaveDelegation(TenantBase):
    """A manager lets someone else decide their direct reports' leave for a date range (e.g. while away)."""

    __tablename__ = "leave_delegations"
    id: Mapped[int] = mapped_column(primary_key=True)
    delegator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delegate_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeaveRequest(TenantBase):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    half_day: Mapped[str | None] = mapped_column(String(8))  # first | second; only for a single-day request (days = 0.5)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("leave_requests.id", ondelete="SET NULL"))  # a revision of approved leave
    decided_via: Mapped[int | None] = mapped_column(Integer)  # delegator whose authority the decision used


class Holiday(TenantBase):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    date: Mapped[date] = mapped_column(Date, unique=True)


class Shift(TenantBase):
    """A work schedule. `start_time`/`end_time` are local wall-clock times; end <= start means it crosses midnight.
    Both empty = flexible shift (only the required hours count)."""

    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    required_hours: Mapped[float] = mapped_column(Float, default=8.0, server_default="8")
    half_day_hours: Mapped[float | None] = mapped_column(Float)
    overtime_after_hours: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attendance(TenantBase):
    """One work session per person per work date (the local date the shift started on)."""

    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date)
    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_mode: Mapped[str] = mapped_column(String(10), default="office", server_default="office")  # office | wfh
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"))
    check_in_lat: Mapped[float | None] = mapped_column(Float)
    check_in_lng: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(12), default="self", server_default="self")  # self | correction | auto
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Frozen when the session is closed, so later shift/holiday edits never rewrite history. NULL = not closed yet
    # (or recorded before this feature): computed on the fly.
    status: Mapped[str | None] = mapped_column(String(16))
    day_type: Mapped[str | None] = mapped_column(String(10))
    worked_minutes: Mapped[int | None] = mapped_column(Integer)
    break_minutes: Mapped[int | None] = mapped_column(Integer)
    late_minutes: Mapped[int | None] = mapped_column(Integer)
    early_minutes: Mapped[int | None] = mapped_column(Integer)
    overtime_minutes: Mapped[int | None] = mapped_column(Integer)

    breaks: Mapped[list["AttendanceBreak"]] = relationship(cascade="all, delete-orphan", order_by="AttendanceBreak.id")

    __table_args__ = (UniqueConstraint("user_id", "work_date", name="uq_attendance_user_date"),)


class AttendanceBreak(TenantBase):
    __tablename__ = "attendance_breaks"
    id: Mapped[int] = mapped_column(primary_key=True)
    attendance_id: Mapped[int] = mapped_column(ForeignKey("attendance.id", ondelete="CASCADE"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceCorrection(TenantBase):
    """A request to fix a day's times (forgot to check out, wrong time, no check-in). Applied only when approved."""

    __tablename__ = "attendance_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    requested_check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending", index=True)  # pending|approved|rejected|cancelled
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    attendance_id: Mapped[int | None] = mapped_column(ForeignKey("attendance.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(TenantBase):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="info")
    link: Mapped[str | None] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)


class Webhook(TenantBase):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    events: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDelivery(TenantBase):
    __tablename__ = "webhook_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    webhook_id: Mapped[int] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|success|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)


class AuditLog(TenantBase):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Setting(TenantBase):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Meeting(TenantBase):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    room_id: Mapped[str] = mapped_column(String(40), unique=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|active|ended
    kind: Mapped[str] = mapped_column(String(10), default="meeting", server_default="meeting")  # meeting | call (one-to-one)
    call_video: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # a call placed as video (False = voice only)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(12))  # calls: answered | declined | missed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    participants: Mapped[list["MeetingParticipant"]] = relationship(cascade="all, delete-orphan")


class MeetingParticipant(TenantBase):
    """Who may join a meeting besides its host. A meeting is private to the host and the people listed here."""

    __tablename__ = "meeting_participants"
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(TenantBase):
    """A direct message (exactly two members, unique `dm_key`) or a named group."""

    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # dm | group
    name: Mapped[str | None] = mapped_column(String(120))
    dm_key: Mapped[str | None] = mapped_column(String(40), unique=True)  # "<low_id>:<high_id>"
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMember(TenantBase):
    __tablename__ = "conversation_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)
    last_delivered_message_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # the newest message this person's client has received
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # per person: keep this chat at the top of their list

    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)


class Message(TenantBase):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)  # the text, a caption, or the sticker id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(10), default="text", server_default="text")  # text | image | audio | file | sticker
    file_name: Mapped[str | None] = mapped_column(String(255))
    stored_name: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(Integer)
    mime: Mapped[str | None] = mapped_column(String(60))
    duration_s: Mapped[int | None] = mapped_column(Integer)  # voice messages and audio
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # soft delete: the row stays so replies and read marks keep working

    __table_args__ = (Index("ix_messages_conversation_id_id", "conversation_id", "id"),)


class MessageReaction(TenantBase):
    __tablename__ = "message_reactions"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)


class BoardProfile(TenantBase):
    """Extra profile for users with role board_member."""

    __tablename__ = "board_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    responsibilities: Mapped[str | None] = mapped_column(Text)
    term_start: Mapped[date | None] = mapped_column(Date)
    permissions: Mapped[list | None] = mapped_column(JSON)  # subset of BOARD_PERMISSIONS


class CommException(TenantBase):
    """Employees the founder allows to message the founder directly (default: blocked)."""

    __tablename__ = "comm_exceptions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Escalation(TenantBase):
    """Structured upward path: employee -> manager/HR -> founder."""

    __tablename__ = "escalations"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(10), default="manager")  # manager | hr | founder (who currently owns it)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | escalated | resolved
    escalated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    escalation_note: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_escalations_level_status", "level", "status"),)


class Team(TenantBase):
    """A working team: owned by a manager, coordinated by a team leader, allocated projects."""

    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    leader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TeamMember(TenantBase):
    """Team membership. A person belongs to at most one team (moving them is a transfer)."""

    __tablename__ = "team_members"
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", name="uq_team_members_user"),)


class TeamProject(TenantBase):
    """A project allocated to a team."""

    __tablename__ = "team_projects"
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TeamReport(TenantBase):
    """Progress report from a team leader to the team's manager."""

    __tablename__ = "team_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    health: Mapped[str] = mapped_column(String(12), default="on_track")  # on_track | at_risk | blocked
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Todo(TenantBase):
    """A person's own to-do item. Top-level rows are main tasks; rows with a parent_id are subtasks (one level only)."""

    __tablename__ = "todos"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("todos.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="medium")  # high | medium | low
    status: Mapped[str] = mapped_column(String(12), default="todo")  # todo | in_progress | completed
    duration_minutes: Mapped[int | None] = mapped_column(Integer)  # estimated effort
    position: Mapped[int] = mapped_column(Integer, default=0)  # order among siblings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ================================================================== payroll
# Money is stored as integer minor units (two decimals assumed) and percentages as basis points (1.25% = 125): exact, no floats.


class SalaryComponent(TenantBase):
    """A company-defined earning or deduction. The platform ships NO statutory rules: rates come from whoever configures them."""

    __tablename__ = "salary_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # earning | deduction
    calc: Mapped[str] = mapped_column(String(20))  # fixed | percent_of_basic | percent_of_gross (deductions only)
    default_value: Mapped[int] = mapped_column(BigInteger, default=0)  # minor units (fixed) or basis points (percent)
    prorate: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    cap_minor: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(300))  # e.g. which rule and which source it was taken from
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Compensation(TenantBase):
    """One version of a person's pay structure, valid from `effective_from`. Never edited: a change is a new version."""

    __tablename__ = "compensations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    basic_minor: Mapped[int] = mapped_column(BigInteger)  # monthly basic
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["CompensationLine"]] = relationship(cascade="all, delete-orphan", order_by="CompensationLine.id")
    __table_args__ = (UniqueConstraint("user_id", "effective_from", name="uq_compensation_user_from"),)


class CompensationLine(TenantBase):
    __tablename__ = "compensation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    compensation_id: Mapped[int] = mapped_column(ForeignKey("compensations.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("salary_components.id", ondelete="RESTRICT"))
    value: Mapped[int] = mapped_column(BigInteger)  # minor units or basis points, depending on the component

    __table_args__ = (UniqueConstraint("compensation_id", "component_id", name="uq_compensation_line"),)


class PayrollRun(TenantBase):
    """Payroll for one calendar month. draft -> processed (submitted by HR) -> approved (a different person) -> paid."""

    __tablename__ = "payroll_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="draft", server_default="draft", index=True)  # draft|processed|approved|paid|cancelled
    note: Mapped[str | None] = mapped_column(String(300))
    settings: Mapped[dict | None] = mapped_column(JSON)  # the policy used (attendance basis, overtime multiplier, ...), frozen with the run
    skipped: Mapped[list | None] = mapped_column(JSON)  # people without a compensation structure, etc.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    processed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_payroll_runs_period", "year", "month"),)


class Payslip(TenantBase):
    __tablename__ = "payslips"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    compensation_id: Mapped[int | None] = mapped_column(ForeignKey("compensations.id", ondelete="SET NULL"))
    currency: Mapped[str] = mapped_column(String(3))
    employee_name: Mapped[str] = mapped_column(String(200))  # snapshot, so a later rename does not change an issued payslip
    employee_code: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(120))
    basic_minor: Mapped[int] = mapped_column(BigInteger)
    gross_minor: Mapped[int] = mapped_column(BigInteger)
    deductions_minor: Mapped[int] = mapped_column(BigInteger)
    net_minor: Mapped[int] = mapped_column(BigInteger)
    facts: Mapped[dict | None] = mapped_column(JSON)  # scheduled/payable days, leave, absences, overtime hours
    warnings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["PayslipLine"]] = relationship(cascade="all, delete-orphan", order_by="PayslipLine.id")
    __table_args__ = (UniqueConstraint("run_id", "user_id", name="uq_payslip_run_user"),)


class PayslipLine(TenantBase):
    __tablename__ = "payslip_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payslips.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    basis: Mapped[str | None] = mapped_column(String(120))
    is_adjustment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


# ================================================================== performance management

class RatingScale(TenantBase):
    __tablename__ = "rating_scales"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    levels: Mapped[list["RatingLevel"]] = relationship(cascade="all, delete-orphan", order_by="RatingLevel.value")


class RatingLevel(TenantBase):
    __tablename__ = "rating_levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    scale_id: Mapped[int] = mapped_column(ForeignKey("rating_scales.id", ondelete="CASCADE"), index=True)
    value: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (UniqueConstraint("scale_id", "value", name="uq_rating_level"),)


class PerformanceCycle(TenantBase):
    """A review period. draft (set up) -> active (reviews exist, goals and reviews can be filled in) -> closed (read-only)."""

    __tablename__ = "performance_cycles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    self_review_due: Mapped[date | None] = mapped_column(Date)
    manager_review_due: Mapped[date | None] = mapped_column(Date)
    scale_id: Mapped[int] = mapped_column(ForeignKey("rating_scales.id"))
    competencies: Mapped[list | None] = mapped_column(JSON)  # the appraisal form: names of the competencies each person is rated on
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Goal(TenantBase):
    """An objective or a measurable KPI for one person in one cycle."""

    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("performance_cycles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(6), default="goal", server_default="goal")  # goal | kpi
    weight: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # percent of the person's objectives; agreed goals add up to at most 100
    unit: Mapped[str | None] = mapped_column(String(30))
    target_value: Mapped[float | None] = mapped_column(Float)
    current_value: Mapped[float | None] = mapped_column(Float)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 0-100; for a KPI derived from current/target
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="proposed", server_default="proposed")  # proposed | agreed | cancelled
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agreed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoalUpdate(TenantBase):
    __tablename__ = "goal_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    progress: Mapped[int | None] = mapped_column(Integer)
    current_value: Mapped[float | None] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PerformanceReview(TenantBase):
    """One appraisal per person per cycle: self review, then manager review, then shared with the person who acknowledges it.
    pending_self -> pending_manager -> completed -> acknowledged. Manager comments stay hidden from the employee until `completed`."""

    __tablename__ = "performance_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("performance_cycles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # the line manager when the cycle was activated
    status: Mapped[str] = mapped_column(String(16), default="pending_self", server_default="pending_self", index=True)
    self_rating: Mapped[int | None] = mapped_column(Integer)
    self_comments: Mapped[str | None] = mapped_column(Text)
    self_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_rating: Mapped[int | None] = mapped_column(Integer)
    manager_comments: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    development_areas: Mapped[str | None] = mapped_column(Text)
    manager_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ratings: Mapped[dict | None] = mapped_column(JSON)  # {"competencies": {name: {"self": n, "manager": n}}, "goals": {goal_id: {...}}}
    goal_score: Mapped[float | None] = mapped_column(Float)  # weighted average of the manager's goal ratings, for reference
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    employee_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("cycle_id", "user_id", name="uq_review_cycle_user"),)


class Feedback(TenantBase):
    """Continuous feedback between colleagues. Seen by the giver, the receiver (if `shared`) and the receiver's line manager / HR in scope."""

    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("performance_cycles.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12), default="praise", server_default="praise")  # praise | constructive
    body: Mapped[str] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmployeeEvent(TenantBase):
    """Append-only employment history: who joined, was promoted, moved, confirmed, suspended, resigned, left or came back, and when.
    Rows are never edited or deleted (they go away only with the person's account)."""

    __tablename__ = "employee_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    effective_date: Mapped[date] = mapped_column(Date)
    from_value: Mapped[dict | None] = mapped_column(JSON)
    to_value: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
