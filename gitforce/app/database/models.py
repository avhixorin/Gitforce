from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_url: Mapped[str] = mapped_column(Text)
    issue_url: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        default=TaskStatus.QUEUED,
        index=True,
    )

    # Optional configuration
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_iterations: Mapped[int | None] = mapped_column(nullable=True)
    test_execution_mode: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    approval_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Workflow data (LangGraph persistent state snapshot)
    state: Mapped[dict] = mapped_column(JSON, default=dict)

    # Enriched data captured during discovery
    repository: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issue: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pr: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    iteration: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(100), index=True)
    agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentChunk(Base):
    """Version-aware repository RAG chunk (Requirement sections 11, 39).

    Stores chunk content plus its embedding as a JSON vector so it works
    across PostgreSQL (pgvector) and SQLite (tests). Indexing is scoped to a
    repository + commit SHA so a task can retrieve code matching the commit
    it is modifying.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "repository_url",
            "commit_sha",
            "path",
            "start_line",
            name="uq_document_chunk_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_url: Mapped[str] = mapped_column(Text, index=True)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)

    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(Text, default="")
    chunk_type: Mapped[str] = mapped_column(String(30), default="module")
    start_line: Mapped[int] = mapped_column(Integer, default=0)
    end_line: Mapped[int] = mapped_column(Integer, default=0)

    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    """Immutable record of a harnessed action (sections 15, 44: audit tool
    execution). Written once; never mutated."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    agent: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    decision: Mapped[str] = mapped_column(String(30), default="allowed")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )