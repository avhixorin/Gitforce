from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from gitforce.app.database.models import TaskStatus


class TaskCreate(BaseModel):
    repository_url: str = Field(..., description="GitHub repository URL")
    issue_url: str = Field(..., description="GitHub issue URL")
    target_branch: str | None = None
    model: str | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    test_execution_mode: str | None = None
    approval_mode: str | None = None


class TaskCreated(BaseModel):
    task_id: str
    status: TaskStatus


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_url: str
    issue_url: str
    status: TaskStatus
    iteration: int
    retry_count: int
    state: dict
    repository: dict | None
    issue: dict | None
    plan: dict | None
    report: dict | None
    pr: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    event: str
    agent: str | None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class HealthOut(BaseModel):
    status: str
    version: str


class MessageOut(BaseModel):
    message: str


class ResumeTask(BaseModel):
    answer: str | None = None