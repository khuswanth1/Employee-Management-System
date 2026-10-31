from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProjectStatus = Literal["planning", "active", "on_hold", "completed"]
TaskStatus = Literal["todo", "in_progress", "review", "changes_requested", "done"]
RiskLevel = Literal["low", "medium", "high", "critical"]
Visibility = Literal["restricted", "company"]
TaskType = Literal["feature", "bug", "improvement", "research", "documentation", "administrative"]
Hours = Annotated[float, Field(ge=0, le=10000)]


def _clean_list(v):
    if v is None:
        return None
    out, seen = [], set()
    for item in v:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    if len(out) > 20 or any(len(i) > 40 for i in out):
        raise ValueError("Use at most 20 entries of 40 characters each")
    return out
Priority = Literal["low", "medium", "high", "urgent"]


class _Dates(BaseModel):
    @model_validator(mode="after")
    def _order(self):
        s, d = getattr(self, "start_date", None), getattr(self, "due_date", None)
        if s and d and d < s:
            raise ValueError("due_date cannot be before start_date")
        return self


class _Normalised(_Dates):
    @field_validator("code", check_fields=False)
    @classmethod
    def _code(cls, v):
        return v.upper() if v else None

    @field_validator("tags", "labels", check_fields=False)
    @classmethod
    def _list(cls, v):
        return _clean_list(v)

    @field_validator("category", "client_name", "title", check_fields=False)
    @classmethod
    def _strip(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class ProjectTeamIn(BaseModel):
    """Team created together with the project: a leader and the members responsible for it."""
    name: str | None = Field(None, min_length=2, max_length=120)  # defaults to "<project> Team"
    leader_id: int | None = None
    member_ids: list[int] = Field(default_factory=list, max_length=200)


class ProjectCreate(_Normalised):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    status: ProjectStatus = "planning"
    start_date: date | None = None
    due_date: date | None = None
    code: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,19}$")
    category: str | None = Field(None, max_length=60)
    client_name: str | None = Field(None, max_length=120)
    risk_level: RiskLevel = "low"
    visibility: Visibility = "restricted"
    estimated_hours: Hours | None = None
    tags: list[str] | None = None
    member_ids: list[int] = []
    team_id: int | None = None          # allocate the new project to an existing team you manage
    team: ProjectTeamIn | None = None   # ... or create a team (leader + members) for it


class ProjectUpdate(_Normalised):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None
    start_date: date | None = None
    due_date: date | None = None
    code: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,19}$")
    category: str | None = Field(None, max_length=60)
    client_name: str | None = Field(None, max_length=120)
    risk_level: RiskLevel | None = None
    visibility: Visibility | None = None
    estimated_hours: Hours | None = None
    tags: list[str] | None = None


class MembersIn(BaseModel):
    member_ids: list[int]


class MilestoneIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    due_date: date | None = None


class MilestoneUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=200)
    due_date: date | None = None
    completed: bool | None = None


class TaskCreate(_Normalised):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = None
    priority: Priority = "medium"
    assignee_id: int | None = None
    milestone_id: int | None = None
    due_date: date | None = None
    task_type: TaskType = "feature"
    labels: list[str] | None = None
    start_date: date | None = None
    estimated_hours: Hours | None = None
    actual_hours: Hours | None = None


class TaskUpdate(_Normalised):
    title: str | None = Field(None, min_length=2, max_length=300)
    description: str | None = None
    priority: Priority | None = None
    assignee_id: int | None = None
    milestone_id: int | None = None
    due_date: date | None = None
    status: TaskStatus | None = None
    progress: int | None = Field(None, ge=0, le=100)
    is_blocked: bool | None = None
    blocker_note: str | None = Field(None, max_length=1000)
    task_type: TaskType | None = None
    labels: list[str] | None = None
    start_date: date | None = None
    estimated_hours: Hours | None = None
    actual_hours: Hours | None = None


class CommentIn(BaseModel):
    body: str = Field(..., max_length=2000)

    @model_validator(mode="after")
    def _not_blank(self):
        self.body = self.body.strip()
        if not self.body:
            raise ValueError("Write something before posting")
        return self


class TaskReview(BaseModel):
    approved: bool
    note: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _note_when_rejected(self):
        if not self.approved and not (self.note and self.note.strip()):
            raise ValueError("A review comment is required when requesting changes")
        return self


class DependenciesIn(BaseModel):
    depends_on: list[int]
