from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.job_models import JobStatus
from agento.framework.job_store import fetch_job, pause_job, resume_job


def _make_row(**overrides) -> dict:
    row = {
        "id": 42,
        "schedule_id": None,
        "type": "cron",
        "source": "jira",
        "agent_view_id": 1,
        "priority": 50,
        "reference_id": "AI-42",
        "agent_type": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "prompt": None,
        "output": None,
        "context": None,
        "idempotency_key": "jira:cron:AI-42:20260220_0800",
        "status": "RUNNING",
        "attempt": 1,
        "max_attempts": 3,
        "scheduled_after": datetime(2026, 2, 20, 8, 0),
        "started_at": datetime(2026, 2, 20, 8, 0, 5),
        "finished_at": None,
        "result_summary": None,
        "error_message": None,
        "error_class": None,
        "pid": 12345,
        "session_id": "sess-abc-123",
        "created_at": datetime(2026, 2, 20, 7, 59),
        "updated_at": datetime(2026, 2, 20, 8, 0, 5),
    }
    row.update(overrides)
    return row


def _mock_conn(row=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn.cursor.return_value.__enter__ = lambda s: cursor
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestFetchJob:
    def test_returns_job_when_found(self):
        conn, _cursor = _mock_conn(_make_row())
        job = fetch_job(conn, 42)
        assert job is not None
        assert job.id == 42
        assert job.status == JobStatus.RUNNING

    def test_returns_none_when_not_found(self):
        conn, _cursor = _mock_conn(None)
        assert fetch_job(conn, 999) is None


class TestPauseJob:
    def test_pause_running_job_with_live_pid(self):
        conn, _cursor = _mock_conn(_make_row(pid=12345))

        with patch("agento.framework.job_store.os.kill") as mock_kill:
            # First os.kill(pid, 0) succeeds (alive), SIGTERM succeeds,
            # then os.kill(pid, 0) raises OSError (dead)
            mock_kill.side_effect = [None, None, OSError("dead")]
            with patch("agento.framework.job_store.time.sleep"):
                job = pause_job(conn, 42)

        assert job.status == JobStatus.PAUSED
        conn.commit.assert_called_once()

    def test_pause_running_job_with_dead_pid(self):
        conn, _cursor = _mock_conn(_make_row(pid=99999))

        with patch("agento.framework.job_store.os.kill", side_effect=OSError("dead")):
            job = pause_job(conn, 42)

        assert job.status == JobStatus.PAUSED
        conn.commit.assert_called_once()

    def test_pause_running_job_without_pid(self):
        conn, _cursor = _mock_conn(_make_row(pid=None))
        job = pause_job(conn, 42)
        assert job.status == JobStatus.PAUSED

    def test_pause_not_found_raises(self):
        conn, _cursor = _mock_conn(None)
        with pytest.raises(ValueError, match="Job not found"):
            pause_job(conn, 999)

    def test_pause_wrong_status_raises(self):
        conn, _cursor = _mock_conn(_make_row(status="SUCCESS"))
        with pytest.raises(ValueError, match="Cannot pause job in status SUCCESS"):
            pause_job(conn, 42)

    def test_pause_paused_job_raises(self):
        conn, _cursor = _mock_conn(_make_row(status="PAUSED"))
        with pytest.raises(ValueError, match="Cannot pause job in status PAUSED"):
            pause_job(conn, 42)


class TestResumeJob:
    def test_resume_paused_job(self):
        conn, _cursor = _mock_conn(_make_row(status="PAUSED", pid=12345, session_id="sess-abc"))
        job = resume_job(conn, 42)
        assert job.status == JobStatus.TODO
        assert job.pid is None
        conn.commit.assert_called_once()

    def test_resume_not_found_raises(self):
        conn, _cursor = _mock_conn(None)
        with pytest.raises(ValueError, match="Job not found"):
            resume_job(conn, 999)

    def test_resume_wrong_status_raises(self):
        conn, _cursor = _mock_conn(_make_row(status="RUNNING"))
        with pytest.raises(ValueError, match="Cannot resume job in status RUNNING"):
            resume_job(conn, 42)

    def test_resume_no_session_id_raises(self):
        conn, _cursor = _mock_conn(_make_row(status="PAUSED", session_id=None))
        with pytest.raises(ValueError, match="no session_id"):
            resume_job(conn, 42)
