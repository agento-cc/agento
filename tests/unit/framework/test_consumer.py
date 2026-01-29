from __future__ import annotations

import logging
import signal
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.consumer import Consumer, _JobResult
from agento.framework.job_models import AgentType, Job, JobStatus
from agento.framework.runner import RunResult
from agento.modules.claude.src.output_parser import ClaudeResult


def _mock_primary_token():
    """Create a mock primary token for consumer._run_job fallback."""
    token = MagicMock()
    token.agent_type = AgentProvider.CLAUDE
    return token


def _mock_resolved_token():
    """Create a mock token returned by TokenResolver.resolve."""
    token = MagicMock()
    token.credentials_path = "/etc/tokens/claude_1.json"
    return token


def _make_job(**overrides) -> Job:
    defaults = dict(
        id=1,
        schedule_id=None,
        type=AgentType.CRON,
        source="jira",
        agent_view_id=None,
        priority=50,
        reference_id="AI-1",
        agent_type=None,
        model=None,
        input_tokens=None,
        output_tokens=None,
        prompt=None,
        output=None,
        context=None,
        idempotency_key="jira:cron:AI-1:20260220_0800",
        status=JobStatus.TODO,
        attempt=0,
        max_attempts=3,
        scheduled_after=datetime(2026, 2, 20, 8, 0),
        started_at=None,
        finished_at=None,
        result_summary=None,
        error_message=None,
        error_class=None,
        created_at=datetime(2026, 2, 20, 7, 59),
        updated_at=datetime(2026, 2, 20, 7, 59),
    )
    defaults.update(overrides)
    return Job(**defaults)


def _mock_connection(row=None):
    """Create mock connection with optional fetchone result."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = row
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _make_row(**overrides) -> dict:
    row = {
        "id": 1,
        "schedule_id": None,
        "type": "cron",
        "source": "jira",
        "agent_view_id": None,
        "priority": 50,
        "reference_id": "AI-1",
        "agent_type": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "prompt": None,
        "output": None,
        "context": None,
        "idempotency_key": "jira:cron:AI-1:20260220_0800",
        "status": "TODO",
        "attempt": 0,
        "max_attempts": 3,
        "scheduled_after": datetime(2026, 2, 20, 8, 0),
        "started_at": None,
        "finished_at": None,
        "result_summary": None,
        "error_message": None,
        "error_class": None,
        "created_at": datetime(2026, 2, 20, 7, 59),
        "updated_at": datetime(2026, 2, 20, 7, 59),
    }
    row.update(overrides)
    return row


def _make_claude_result(**overrides) -> ClaudeResult:
    defaults = dict(
        raw_output="ok",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
        num_turns=3,
        duration_ms=5000,
        subtype="success",
        agent_type="claude",
        prompt=None,
    )
    defaults.update(overrides)
    return ClaudeResult(**defaults)


# ---- Section 4: Stale job recovery ----


class TestRecoverStaleJobs:
    @patch("agento.framework.consumer.get_connection")
    def test_recover_resets_stale_jobs(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_cursor.rowcount = 2  # simulate 2 rows affected per UPDATE
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._recover_stale_jobs()

        # Two UPDATE calls: one for TODO reset, one for DEAD
        assert mock_cursor.execute.call_count == 2
        first_sql = mock_cursor.execute.call_args_list[0][0][0]
        second_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "status = 'TODO'" in first_sql
        assert "status = 'DEAD'" in second_sql
        mock_conn.commit.assert_called_once()

    @patch("agento.framework.consumer.get_connection")
    def test_recover_uses_timeout_plus_buffer(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_cursor.rowcount = 0
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._recover_stale_jobs()

        threshold = sample_consumer_config.job_timeout_seconds + 60
        first_params = mock_cursor.execute.call_args_list[0][0][1]
        assert first_params == (threshold,)

    @patch("agento.framework.consumer.get_connection")
    def test_recover_db_error_does_not_crash(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_get_conn.side_effect = RuntimeError("DB down")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))

        # Should not raise
        consumer._recover_stale_jobs()


# ---- Section 5: Dequeue ----


class TestDequeue:
    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_empty_queue(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, _mock_cursor = _mock_connection(row=None)
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        result = consumer._try_dequeue()

        assert result is None
        mock_conn.rollback.assert_called_once()

    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_claims_job(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        row = _make_row()
        mock_conn, _mock_cursor = _mock_connection(row=row)
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = consumer._try_dequeue()

        assert job is not None
        assert job.status == JobStatus.RUNNING
        mock_conn.commit.assert_called_once()

    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_increments_attempt(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        row = _make_row(attempt=2)
        mock_conn, _mock_cursor = _mock_connection(row=row)
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = consumer._try_dequeue()

        assert job is not None
        assert job.attempt == 3  # 2 + 1

    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_error_returns_none(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_cursor.execute.side_effect = RuntimeError("DB error")
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        result = consumer._try_dequeue()

        assert result is None
        mock_conn.rollback.assert_called_once()

    @patch("agento.framework.consumer.get_connection")
    def test_dequeue_always_closes_connection(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        # Success path
        row = _make_row()
        mock_conn, _mock_cursor = _mock_connection(row=row)
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._try_dequeue()
        mock_conn.close.assert_called_once()

        # Failure path
        mock_conn2, mock_cursor2 = _mock_connection()
        mock_cursor2.execute.side_effect = RuntimeError("fail")
        mock_get_conn.return_value = mock_conn2

        consumer._try_dequeue()
        mock_conn2.close.assert_called_once()


# ---- Section 6: Execution dispatch ----


class TestRunJob:
    @pytest.fixture(autouse=True)
    def _mock_runtime(self):
        from agento.framework.agent_view_runtime import AgentViewRuntime
        with patch("agento.framework.consumer.resolve_agent_view_runtime",
                   return_value=AgentViewRuntime()):
            yield

    @pytest.fixture(autouse=True)
    def _mock_token_resolver(self):
        with patch("agento.framework.consumer.TokenResolver") as MockCls:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = _mock_resolved_token()
            MockCls.return_value = mock_resolver
            self._token_resolver_mock = mock_resolver
            yield

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_cron(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow

        mock_channel = MagicMock()
        mock_channel.name = "jira"
        mock_get_ch.return_value = mock_channel

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(type=AgentType.CRON, reference_id="AI-1")

        result = consumer._run_job(job)

        mock_get_ch.assert_called_once_with("jira")
        mock_get_wf.assert_called_once_with(AgentType.CRON)
        mock_workflow.execute_job.assert_called_once()
        assert mock_workflow.execute_job.call_args[0][:2] == (mock_channel, job)
        MockRunner.assert_called_once_with(
            AgentProvider.CLAUDE, logger=consumer.logger, dry_run=False,
            timeout_seconds=sample_consumer_config.job_timeout_seconds,
            model_override=None,
            working_dir=None,
            credentials_path="/etc/tokens/claude_1.json",
        )
        assert isinstance(result, _JobResult)
        assert "subtype=" in result.summary

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_cron_no_reference_id_raises(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_get_ch.return_value = MagicMock(name="jira")
        mock_workflow = MagicMock()
        mock_workflow.execute_job.side_effect = ValueError("Cron job 1 has no reference_id")
        mock_get_wf.return_value.return_value = mock_workflow

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(type=AgentType.CRON, reference_id=None)

        with pytest.raises(ValueError, match="no reference_id"):
            consumer._run_job(job)

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_todo_specific(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow

        mock_channel = MagicMock()
        mock_channel.name = "jira"
        mock_get_ch.return_value = mock_channel

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(type=AgentType.TODO, reference_id="AI-2")

        result = consumer._run_job(job)

        mock_workflow.execute_job.assert_called_once()
        assert mock_workflow.execute_job.call_args[0][:2] == (mock_channel, job)
        assert isinstance(result, _JobResult)
        assert "subtype=" in result.summary

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_todo_no_ref_delegates_to_workflow(
        self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary,
        sample_config, sample_db_config, sample_consumer_config,
    ):
        """Consumer passes through to workflow — no TODO-specific branching."""
        mock_conn.return_value = MagicMock()
        no_work_result = RunResult(raw_output="No TODO tasks found", subtype="no_work")
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = no_work_result
        mock_get_wf.return_value.return_value = mock_workflow

        mock_channel = MagicMock()
        mock_channel.name = "jira"
        mock_get_ch.return_value = mock_channel

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(type=AgentType.TODO, reference_id=None)

        result = consumer._run_job(job)

        mock_workflow.execute_job.assert_called_once()
        assert isinstance(result, _JobResult)
        assert result.summary == "No TODO tasks found"

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_followup(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow

        mock_channel = MagicMock()
        mock_channel.name = "jira"
        mock_get_ch.return_value = mock_channel

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(
            type=AgentType.FOLLOWUP,
            reference_id="AI-3",
            context="Sprawdź czy reindeks się zakończył",
            source="jira",
        )

        result = consumer._run_job(job)

        mock_workflow.execute_job.assert_called_once()
        assert mock_workflow.execute_job.call_args[0][:2] == (mock_channel, job)
        assert isinstance(result, _JobResult)
        assert "subtype=" in result.summary

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_followup_no_reference_id_raises(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_get_ch.return_value = MagicMock(name="jira")
        mock_workflow = MagicMock()
        mock_workflow.execute_job.side_effect = ValueError("Followup job 1 has no reference_id")
        mock_get_wf.return_value.return_value = mock_workflow

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(
            type=AgentType.FOLLOWUP,
            reference_id=None,
            context="some instructions",
        )

        with pytest.raises(ValueError, match="no reference_id"):
            consumer._run_job(job)

    @patch("agento.framework.consumer.get_primary_token", return_value=_mock_primary_token())
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_followup_no_context_raises(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, mock_primary, sample_config, sample_db_config, sample_consumer_config):
        mock_conn.return_value = MagicMock()
        mock_get_ch.return_value = MagicMock(name="jira")
        mock_workflow = MagicMock()
        mock_workflow.execute_job.side_effect = ValueError("Followup job 1 has no context")
        mock_get_wf.return_value.return_value = mock_workflow

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(
            type=AgentType.FOLLOWUP,
            reference_id="AI-3",
            context=None,
        )

        with pytest.raises(ValueError, match="no context"):
            consumer._run_job(job)

    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    def test_run_job_no_provider_no_primary_raises(self, mock_conn, MockRunner, mock_get_ch, mock_get_wf, sample_config, sample_db_config, sample_consumer_config):
        """When no agent/provider in config and no primary token, consumer raises."""
        mock_conn.return_value = MagicMock()

        with patch("agento.framework.consumer.get_primary_token", return_value=None):
            consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
            job = _make_job(type=AgentType.CRON, reference_id="AI-1")

            with pytest.raises(RuntimeError, match="No agent/provider configured"):
                consumer._run_job(job)

        # TokenResolver.resolve should never be reached — error raised before token selection
        self._token_resolver_mock.resolve.assert_not_called()



# ---- Section 7: Finalization ----


class TestFinalize:
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_success(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)
        job_result = _JobResult(
            summary="done",
            agent_type="claude",
            model="claude-sonnet-4",
            input_tokens=100,
            output_tokens=50,
            prompt="the prompt",
            output='{"result": "ok"}',
        )

        consumer._finalize_job(job, error=None, job_result=job_result, elapsed_ms=1000)

        mock_cursor.execute.assert_called_once()
        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "SUCCESS" in sql_arg
        assert "agent_type" in sql_arg
        assert "model" in sql_arg
        assert "prompt" in sql_arg
        assert "output" in sql_arg
        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == "done"               # result_summary
        assert params[1] == "claude"             # agent_type
        assert params[2] == "claude-sonnet-4"    # model
        assert params[3] == 100                  # input_tokens
        assert params[4] == 50                   # output_tokens
        assert params[5] == "the prompt"         # prompt
        assert params[6] == '{"result": "ok"}'   # output
        mock_conn.commit.assert_called_once()

    @patch("agento.framework.consumer.get_connection")
    def test_finalize_success_with_none_result(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)

        consumer._finalize_job(job, error=None, job_result=None, elapsed_ms=1000)

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] is None  # result_summary
        assert params[1] is None  # agent_type
        assert params[2] is None  # model

    @patch("agento.framework.consumer.evaluate_retry")
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_retryable_failure(self, mock_get_conn, mock_eval, sample_config, sample_db_config, sample_consumer_config):
        from agento.framework.retry_policy import RetryDecision

        mock_eval.return_value = RetryDecision(should_retry=True, delay_seconds=60, reason="retry")

        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)

        consumer._finalize_job(
            job, error=RuntimeError("timeout"), job_result=None, elapsed_ms=5000
        )

        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "TODO" in sql_arg
        assert "scheduled_after" in sql_arg
        mock_conn.commit.assert_called_once()

    @patch("agento.framework.consumer.evaluate_retry")
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_non_retryable_failure(self, mock_get_conn, mock_eval, sample_config, sample_db_config, sample_consumer_config):
        from agento.framework.retry_policy import RetryDecision

        mock_eval.return_value = RetryDecision(
            should_retry=False, delay_seconds=0, reason="non-retryable"
        )

        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)

        consumer._finalize_job(
            job, error=ValueError("bad input"), job_result=None, elapsed_ms=100
        )

        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "DEAD" in sql_arg
        mock_conn.commit.assert_called_once()

    @patch("agento.framework.consumer.evaluate_retry")
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_max_attempts_reached(self, mock_get_conn, mock_eval, sample_config, sample_db_config, sample_consumer_config):
        from agento.framework.retry_policy import RetryDecision

        mock_eval.return_value = RetryDecision(
            should_retry=False, delay_seconds=0, reason="Max attempts (3) reached"
        )

        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=3, max_attempts=3)

        consumer._finalize_job(
            job, error=RuntimeError("fail"), job_result=None, elapsed_ms=100
        )

        sql_arg = mock_cursor.execute.call_args[0][0]
        assert "DEAD" in sql_arg

    @patch("agento.framework.consumer.evaluate_retry")
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_error_message_truncated(self, mock_get_conn, mock_eval, sample_config, sample_db_config, sample_consumer_config):
        from agento.framework.retry_policy import RetryDecision

        mock_eval.return_value = RetryDecision(
            should_retry=False, delay_seconds=0, reason="dead"
        )

        mock_conn, mock_cursor = _mock_connection()
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)

        long_error = RuntimeError("x" * 3000)
        consumer._finalize_job(job, error=long_error, job_result=None, elapsed_ms=100)

        params = mock_cursor.execute.call_args[0][1]
        error_msg = params[0]
        assert len(error_msg) <= 2000

    @patch("agento.framework.consumer.get_connection")
    def test_finalize_db_error_does_not_crash(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_cursor.execute.side_effect = RuntimeError("DB down")
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)
        job_result = _JobResult(summary="ok")

        # Should not raise (retries 3 times then gives up)
        consumer._finalize_job(job, error=None, job_result=job_result, elapsed_ms=100)

        assert mock_conn.rollback.call_count == 3  # 3 retry attempts

    @patch("agento.framework.consumer.time.sleep")
    @patch("agento.framework.consumer.get_connection")
    def test_finalize_retries_on_db_error_then_succeeds(self, mock_get_conn, mock_sleep, sample_config, sample_db_config, sample_consumer_config):
        """DB fails on first attempt, succeeds on second."""
        fail_conn, fail_cursor = _mock_connection()
        fail_cursor.execute.side_effect = RuntimeError("DB down")

        ok_conn, _ok_cursor = _mock_connection()

        mock_get_conn.side_effect = [fail_conn, ok_conn]

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(attempt=1)
        job_result = _JobResult(summary="ok")

        consumer._finalize_job(job, error=None, job_result=job_result, elapsed_ms=100)

        fail_conn.rollback.assert_called_once()
        ok_conn.commit.assert_called_once()
        mock_sleep.assert_called_once_with(1)


# ---- Section 8: Lifecycle ----


class TestLifecycle:
    def test_shutdown_on_sigterm(self, sample_config, sample_db_config, sample_consumer_config):
        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        assert not consumer._shutdown.is_set()

        consumer._handle_signal(signal.SIGTERM, None)

        assert consumer._shutdown.is_set()

    @patch("agento.framework.consumer.get_connection")
    def test_poll_loop_exits_on_shutdown(self, mock_get_conn, sample_config, sample_db_config, sample_consumer_config):
        mock_conn, _mock_cursor = _mock_connection(row=None)
        mock_get_conn.return_value = mock_conn

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._shutdown.set()  # Pre-set shutdown

        # run() should exit quickly without blocking
        consumer.run()
