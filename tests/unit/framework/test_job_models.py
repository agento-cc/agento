from __future__ import annotations

from datetime import datetime

import pytest

from agento.framework.job_models import AgentType, Job, JobStatus


def _make_row(**overrides) -> dict:
    row = {
        "id": 1,
        "schedule_id": 10,
        "type": "cron",
        "source": "jira",
        "agent_view_id": None,
        "priority": 50,
        "reference_id": "AI-123",
        "agent_type": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "prompt": None,
        "output": None,
        "context": None,
        "idempotency_key": "jira:cron:AI-123:20260220_0800",
        "status": "TODO",
        "attempt": 0,
        "max_attempts": 3,
        "scheduled_after": datetime(2026, 2, 20, 8, 0),
        "started_at": datetime(2026, 2, 20, 8, 0, 5),
        "finished_at": None,
        "result_summary": None,
        "error_message": None,
        "error_class": None,
        "created_at": datetime(2026, 2, 20, 7, 59),
        "updated_at": datetime(2026, 2, 20, 8, 0, 5),
    }
    row.update(overrides)
    return row


def test_job_from_row():
    row = _make_row()
    job = Job.from_row(row)

    assert job.id == 1
    assert job.schedule_id == 10
    assert job.type == AgentType.CRON
    assert job.source == "jira"
    assert job.reference_id == "AI-123"
    assert job.idempotency_key == "jira:cron:AI-123:20260220_0800"
    assert job.status == JobStatus.TODO
    assert job.attempt == 0
    assert job.max_attempts == 3
    assert job.started_at == datetime(2026, 2, 20, 8, 0, 5)


def test_job_from_row_nullable_fields():
    row = _make_row(schedule_id=None, reference_id=None, started_at=None, finished_at=None)
    job = Job.from_row(row)

    assert job.schedule_id is None
    assert job.reference_id is None
    assert job.started_at is None
    assert job.finished_at is None


def test_job_from_row_with_context():
    row = _make_row(type="followup", context="Sprawdź reindeks", source="agent")
    job = Job.from_row(row)

    assert job.type == AgentType.FOLLOWUP
    assert job.context == "Sprawdź reindeks"
    assert job.source == "agent"


def test_job_from_row_context_none():
    row = _make_row()
    job = Job.from_row(row)

    assert job.context is None


def test_job_from_row_tracking_fields():
    row = _make_row(
        agent_type="claude",
        model="claude-sonnet-4-20250514",
        input_tokens=1500,
        output_tokens=800,
        prompt="Zadanie cykliczne AI-123",
        output='{"result": "ok"}',
    )
    job = Job.from_row(row)

    assert job.agent_type == "claude"
    assert job.model == "claude-sonnet-4-20250514"
    assert job.input_tokens == 1500
    assert job.output_tokens == 800
    assert job.prompt == "Zadanie cykliczne AI-123"
    assert job.output == '{"result": "ok"}'


def test_job_from_row_defaults_tracking_fields_missing():
    # Old-style row without tracking columns (uses .get())
    row = _make_row()
    del row["agent_type"]
    del row["model"]
    del row["input_tokens"]
    del row["output_tokens"]
    del row["prompt"]
    del row["output"]
    job = Job.from_row(row)

    assert job.agent_type is None
    assert job.model is None
    assert job.input_tokens is None
    assert job.output_tokens is None
    assert job.prompt is None
    assert job.output is None


def test_agent_type_enum():
    assert AgentType("cron") == AgentType.CRON
    assert AgentType("todo") == AgentType.TODO
    assert AgentType("followup") == AgentType.FOLLOWUP
    with pytest.raises(ValueError):
        AgentType("invalid")


def test_job_status_enum():
    assert JobStatus("TODO") == JobStatus.TODO
    assert JobStatus("RUNNING") == JobStatus.RUNNING
    assert JobStatus("SUCCESS") == JobStatus.SUCCESS
    assert JobStatus("FAILED") == JobStatus.FAILED
    assert JobStatus("DEAD") == JobStatus.DEAD
    assert JobStatus("PAUSED") == JobStatus.PAUSED
