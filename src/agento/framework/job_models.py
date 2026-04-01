from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class AgentType(Enum):
    CRON = "cron"
    TODO = "todo"
    FOLLOWUP = "followup"
    BLANK = "blank"


class JobStatus(Enum):
    TODO = "TODO"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DEAD = "DEAD"


@dataclass
class Job:
    id: int
    schedule_id: int | None
    type: AgentType
    source: str
    agent_view_id: int | None
    priority: int
    reference_id: str | None
    agent_type: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    prompt: str | None
    output: str | None
    context: str | None
    idempotency_key: str
    status: JobStatus
    attempt: int
    max_attempts: int
    scheduled_after: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_summary: str | None
    error_message: str | None
    error_class: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def stub(
        cls,
        *,
        type: AgentType,
        source: str,
        reference_id: str | None = None,
        agent_view_id: int | None = None,
        priority: int = 50,
        context: str | None = None,
    ) -> Job:
        """Create a minimal Job for CLI / testing (no DB row)."""
        now = datetime.now(UTC)
        return cls(
            id=0, schedule_id=None, type=type, source=source,
            agent_view_id=agent_view_id, priority=priority,
            reference_id=reference_id, agent_type=None, model=None,
            input_tokens=None, output_tokens=None, prompt=None, output=None,
            context=context, idempotency_key="", status=JobStatus.RUNNING,
            attempt=1, max_attempts=3, scheduled_after=now, started_at=now,
            finished_at=None, result_summary=None, error_message=None,
            error_class=None, created_at=now, updated_at=now,
        )

    @classmethod
    def from_row(cls, row: dict) -> Job:
        return cls(
            id=row["id"],
            schedule_id=row["schedule_id"],
            type=AgentType(row["type"]),
            source=row["source"],
            agent_view_id=row.get("agent_view_id"),
            priority=row.get("priority", 50),
            reference_id=row["reference_id"],
            agent_type=row.get("agent_type"),
            model=row.get("model"),
            input_tokens=row.get("input_tokens"),
            output_tokens=row.get("output_tokens"),
            prompt=row.get("prompt"),
            output=row.get("output"),
            context=row.get("context"),
            idempotency_key=row["idempotency_key"],
            status=JobStatus(row["status"]),
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            scheduled_after=row["scheduled_after"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result_summary=row["result_summary"],
            error_message=row["error_message"],
            error_class=row["error_class"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
