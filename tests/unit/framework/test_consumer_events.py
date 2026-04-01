"""Tests for event dispatching from Consumer."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.consumer import Consumer, _JobResult
from agento.framework.event_manager import ObserverEntry, get_event_manager
from agento.framework.event_manager import clear as clear_event_manager
from agento.framework.events import (
    JobClaimedEvent,
    JobDeadEvent,
    JobFailedEvent,
    JobRetryingEvent,
    JobSucceededEvent,
)
from agento.framework.job_models import AgentType, Job


@pytest.fixture(autouse=True)
def _clean():
    clear_event_manager()
    yield
    clear_event_manager()


def _make_job(**overrides) -> Job:
    job = Job.stub(type=AgentType.CRON, source="jira", reference_id="TEST-1")
    job.id = overrides.get("id", 1)
    for k, v in overrides.items():
        setattr(job, k, v)
    return job


def _mock_configs():
    from agento.framework.consumer_config import ConsumerConfig
    from agento.framework.database_config import DatabaseConfig
    db = DatabaseConfig()
    consumer = ConsumerConfig(job_timeout_seconds=60, disable_llm=True)
    return db, consumer


class _EventCollector:
    """Observer that collects dispatched events."""

    events: list = []  # noqa: RUF012

    def execute(self, event: object) -> None:
        _EventCollector.events.append(event)

    @classmethod
    def reset(cls):
        cls.events = []


@pytest.fixture(autouse=True)
def _reset_collector():
    _EventCollector.reset()
    yield


class TestFinalizeJobEvents:
    def _make_consumer(self):
        db, consumer = _mock_configs()
        return Consumer(db, consumer, MagicMock())

    @patch("agento.framework.consumer.get_connection")
    def test_success_dispatches_job_succeeded(self, mock_conn):
        mock_conn.return_value = MagicMock()
        em = get_event_manager()
        em.register("job_succeeded", ObserverEntry(name="col", observer_class=_EventCollector))

        consumer = self._make_consumer()
        job = _make_job()
        result = _JobResult(summary="done", agent_type="claude", model="opus")

        consumer._finalize_job(job, None, result, 500)

        assert len(_EventCollector.events) == 1
        evt = _EventCollector.events[0]
        assert isinstance(evt, JobSucceededEvent)
        assert evt.job is job
        assert evt.summary == "done"
        assert evt.elapsed_ms == 500

    @patch("agento.framework.consumer.get_connection")
    def test_retryable_failure_dispatches_failed_and_retrying(self, mock_conn):
        mock_conn.return_value = MagicMock()
        em = get_event_manager()
        em.register("job_failed", ObserverEntry(name="f", observer_class=_EventCollector))
        em.register("job_retrying", ObserverEntry(name="r", observer_class=_EventCollector))

        consumer = self._make_consumer()
        job = _make_job(attempt=1, max_attempts=3)
        error = RuntimeError("transient")

        consumer._finalize_job(job, error, None, 100)

        types = [type(e) for e in _EventCollector.events]
        assert JobFailedEvent in types
        assert JobRetryingEvent in types

    @patch("agento.framework.consumer.get_connection")
    def test_non_retryable_failure_dispatches_failed_and_dead(self, mock_conn):
        mock_conn.return_value = MagicMock()
        em = get_event_manager()
        em.register("job_failed", ObserverEntry(name="f", observer_class=_EventCollector))
        em.register("job_dead", ObserverEntry(name="d", observer_class=_EventCollector))

        consumer = self._make_consumer()
        # ValueError is non-retryable per retry_policy
        job = _make_job(attempt=1, max_attempts=3)
        error = ValueError("bad input")

        consumer._finalize_job(job, error, None, 100)

        types = [type(e) for e in _EventCollector.events]
        assert JobFailedEvent in types
        assert JobDeadEvent in types


class TestDequeueEvents:
    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_dispatches_job_claimed(self, mock_get_conn):
        from datetime import datetime

        em = get_event_manager()
        em.register("job_claimed", ObserverEntry(name="c", observer_class=_EventCollector))

        now = datetime.now(UTC)
        row = {
            "id": 1, "schedule_id": None, "type": "cron", "source": "jira",
            "agent_view_id": None, "priority": 50,
            "reference_id": "TEST-1", "agent_type": None, "model": None,
            "input_tokens": None, "output_tokens": None, "prompt": None,
            "output": None, "context": None,
            "status": "TODO", "attempt": 0, "max_attempts": 3,
            "scheduled_after": now, "started_at": None,
            "finished_at": None, "result_summary": None,
            "error_message": None, "error_class": None,
            "idempotency_key": "key-1",
            "created_at": now, "updated_at": now,
        }

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = row

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        db, consumer_config = _mock_configs()
        consumer = Consumer(db, consumer_config, MagicMock())
        job = consumer._try_dequeue()

        assert job is not None
        assert len(_EventCollector.events) == 1
        assert isinstance(_EventCollector.events[0], JobClaimedEvent)
