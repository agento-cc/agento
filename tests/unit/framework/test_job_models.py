from __future__ import annotations

from datetime import datetime

import pytest

from agento.framework.job_models import (
    AgentType,
    Job,
    JobRequester,
    JobStatus,
    RequesterTrust,
    normalize_email,
)


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
        "requester_key": None,
        "requester_email": None,
        "requester_trust": "claimed",
        "requester_meta": None,
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


# --- Requester metadata ---


def test_job_from_row_requester_trust_mapping():
    assert Job.from_row(_make_row(requester_trust="domain")).requester_trust is RequesterTrust.DOMAIN
    assert Job.from_row(_make_row(requester_trust="account")).requester_trust is RequesterTrust.ACCOUNT
    # missing column -> CLAIMED
    row = _make_row()
    del row["requester_trust"]
    assert Job.from_row(row).requester_trust is RequesterTrust.CLAIMED
    # SQL NULL -> CLAIMED
    assert Job.from_row(_make_row(requester_trust=None)).requester_trust is RequesterTrust.CLAIMED


def test_job_from_row_requester_fields():
    job = Job.from_row(_make_row(
        requester_key="jira:abc",
        requester_email="user@example.com",
        requester_meta={"basis": "comment_author"},
    ))
    assert job.requester_key == "jira:abc"
    assert job.requester_email == "user@example.com"
    assert job.requester_meta == {"basis": "comment_author"}


def test_job_from_row_requester_meta_dict_stays_dict():
    job = Job.from_row(_make_row(requester_meta={"k": "v"}))
    assert isinstance(job.requester_meta, dict)
    assert job.requester_meta == {"k": "v"}


def test_job_from_row_requester_meta_json_string_parses_to_dict():
    # PyMySQL returns JSON columns as str
    job = Job.from_row(_make_row(requester_meta='{"basis": "reporter", "n": 2}'))
    assert job.requester_meta == {"basis": "reporter", "n": 2}


def test_job_from_row_requester_meta_non_dict_coerced_to_none():
    # tampered/legacy rows: JSON array or scalar string must coerce to None, not raise
    assert Job.from_row(_make_row(requester_meta="[1, 2]")).requester_meta is None
    assert Job.from_row(_make_row(requester_meta='"x"')).requester_meta is None


def test_job_stub_requester_defaults():
    job = Job.stub(type=AgentType.TODO, source="jira")
    assert job.requester_key is None
    assert job.requester_email is None
    assert job.requester_trust is RequesterTrust.CLAIMED
    assert job.requester_meta is None


def test_normalize_email():
    assert normalize_email(None) is None
    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"
    assert normalize_email("") is None
    assert normalize_email("   ") is None


def test_job_requester_blank_key_raises():
    with pytest.raises(ValueError):
        JobRequester(key="   ")


def test_job_requester_non_string_key_raises_value_error_not_attribute_error():
    with pytest.raises(ValueError):
        JobRequester(key=123)  # type: ignore[arg-type]


def test_job_requester_key_stripped():
    assert JobRequester(key="  jira:abc  ").key == "jira:abc"


def test_job_requester_email_normalized():
    assert JobRequester(key="k", email="  USER@Example.com ").email == "user@example.com"
    assert JobRequester(key="k", email="").email is None


def test_job_requester_non_enum_trust_raises():
    with pytest.raises(ValueError):
        JobRequester(key="k", trust="account")  # type: ignore[arg-type]


def test_job_requester_meta_shallow_copied():
    src = {"a": 1}
    r = JobRequester(key="k", meta=src)
    src["a"] = 999
    assert r.meta == {"a": 1}


def test_contracts_facade_exports_requester_types():
    from agento.framework.contracts import JobRequester as CJobRequester
    from agento.framework.contracts import RequesterTrust as CRequesterTrust

    assert CJobRequester is JobRequester
    assert CRequesterTrust is RequesterTrust
