from typing import Literal

from pydantic import BaseModel, Field

Health = Literal["on_track", "at_risk", "blocked"]


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    department_id: int | None = None
    branch_id: int | None = None       # founder (or a branchless manager); a branch manager's team is always in their branch
    manager_id: int | None = None      # founder only; managers own the teams they create
    leader_id: int | None = None
    member_ids: list[int] = Field(default_factory=list, max_length=200)
    project_ids: list[int] = Field(default_factory=list, max_length=100)


class TeamUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    department_id: int | None = None
    branch_id: int | None = None
    is_active: bool | None = None


class MembersIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)


class LeaderIn(BaseModel):
    user_id: int | None = None


class ReassignIn(BaseModel):
    manager_id: int


class ProjectIn(BaseModel):
    project_id: int


class TransferIn(BaseModel):
    user_id: int
    to_team_id: int
    note: str | None = Field(None, max_length=500)


class ReportIn(BaseModel):
    summary: str = Field(min_length=3, max_length=5000)
    health: Health = "on_track"
    project_id: int | None = None


class UpdateReviewIn(BaseModel):
    status: Literal["reviewed", "needs_changes"]
    comment: str | None = Field(None, max_length=2000)
