"""Tests for consumer agent_view integration — scoped config, populate_agent_configs, run_dir."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_view_runtime import AgentViewRuntime
from agento.framework.consumer import Consumer
from agento.framework.job_models import AgentType, Job, JobStatus
from agento.framework.workspace import AgentView, Workspace
from agento.modules.claude.src.output_parser import ClaudeResult


def _make_job(**overrides) -> Job:
    defaults = dict(
        id=42,
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


def _make_runtime_with_agent_view(
    agent_view_id: int = 2,
    workspace_id: int = 1,
    provider: str = "claude",
    model: str = "opus-4",
    scoped_overrides: dict | None = None,
) -> AgentViewRuntime:
    """Create a runtime with a real agent_view + workspace."""
    now = datetime.now(UTC)
    return AgentViewRuntime(
        agent_view=AgentView(
            id=agent_view_id, workspace_id=workspace_id,
            code="developer", label="Developer",
            is_active=True, created_at=now, updated_at=now,
        ),
        workspace=Workspace(
            id=workspace_id, code="acme", label="Acme Corp",
            is_active=True, created_at=now, updated_at=now,
        ),
        provider=provider,
        model=model,
        priority=50,
        scoped_overrides=scoped_overrides or {
            "agent_view/mcp/servers": (
                '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}',
                False,
            ),
            "agent_view/claude/model": ("opus-4", False),
        },
    )


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


class TestRunJobWithAgentView:
    """Tests for _run_job when job has agent_view_id set."""

    @pytest.fixture(autouse=True)
    def _mock_token_resolver(self):
        with patch("agento.framework.consumer.TokenResolver") as MockCls:
            mock_resolver = MagicMock()
            token = MagicMock()
            token.credentials_path = "/etc/tokens/claude_1.json"
            mock_resolver.resolve.return_value = token
            MockCls.return_value = mock_resolver
            yield

    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.populate_agent_configs")
    @patch("agento.framework.consumer.prepare_run_dir")
    @patch("agento.framework.consumer.build_run_dir", return_value="/workspace/acme/developer/runs/42")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_calls_populate_agent_configs_with_agent_view_id(
        self, mock_resolve, mock_build, mock_prepare, mock_populate,
        mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        sample_db_config, sample_consumer_config,
    ):
        runtime = _make_runtime_with_agent_view(agent_view_id=2)
        mock_resolve.return_value = runtime
        mock_conn.return_value = MagicMock()

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        job = _make_job(agent_view_id=2)

        consumer._run_job(job)

        mock_populate.assert_called_once_with(
            "/workspace/acme/developer/runs/42",
            runtime.scoped_overrides,
            agent_view_id=2,
        )

    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.populate_agent_configs")
    @patch("agento.framework.consumer.prepare_run_dir")
    @patch("agento.framework.consumer.build_run_dir", return_value="/workspace/acme/developer/runs/42")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_runner_receives_run_dir(
        self, mock_resolve, mock_build, mock_prepare, mock_populate,
        mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        sample_db_config, sample_consumer_config,
    ):
        mock_resolve.return_value = _make_runtime_with_agent_view()
        mock_conn.return_value = MagicMock()

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._run_job(_make_job(agent_view_id=2))

        MockRunner.assert_called_once()
        assert MockRunner.call_args.kwargs["working_dir"] == "/workspace/acme/developer/runs/42"

    @patch("agento.framework.consumer.get_primary_token")
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_no_agent_view_skips_populate(
        self, mock_resolve, mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        mock_primary, sample_db_config, sample_consumer_config,
    ):
        """Job with agent_view_id=None uses global config, no run_dir."""
        mock_resolve.return_value = AgentViewRuntime()  # defaults: no agent_view
        mock_conn.return_value = MagicMock()
        primary = MagicMock()
        primary.agent_type = AgentProvider.CLAUDE
        mock_primary.return_value = primary

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._run_job(_make_job(agent_view_id=None))

        MockRunner.assert_called_once()
        assert MockRunner.call_args.kwargs["working_dir"] is None

    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.populate_agent_configs")
    @patch("agento.framework.consumer.prepare_run_dir")
    @patch("agento.framework.consumer.build_run_dir", return_value="/workspace/acme/developer/runs/42")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_scoped_overrides_generate_mcp_config_with_agent_view_id(
        self, mock_resolve, mock_build, mock_prepare, mock_populate,
        mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        sample_db_config, sample_consumer_config, tmp_path,
    ):
        """End-to-end: populate_agent_configs writes .mcp.json with agent_view_id in URL."""
        from agento.framework.agent_config_writer import populate_agent_configs as real_populate

        runtime = _make_runtime_with_agent_view(agent_view_id=5)
        mock_resolve.return_value = runtime
        mock_conn.return_value = MagicMock()

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        # Actually call populate to verify .mcp.json content
        wd = tmp_path / "run"
        real_populate(wd, runtime.scoped_overrides, agent_view_id=5)

        mcp_config = json.loads((wd / ".mcp.json").read_text())
        url = mcp_config["mcpServers"]["toolbox"]["url"]
        assert "agent_view_id=5" in url

        # Also verify .claude.json was generated
        claude_config = json.loads((wd / ".claude.json").read_text())
        assert claude_config["model"] == "opus-4"


class TestRunJobProviderFallback:
    """Tests for provider fallback: agent_view config > primary token."""

    @pytest.fixture(autouse=True)
    def _mock_token_resolver(self):
        with patch("agento.framework.consumer.TokenResolver") as MockCls:
            mock_resolver = MagicMock()
            token = MagicMock()
            token.credentials_path = "/etc/tokens/codex_1.json"
            mock_resolver.resolve.return_value = token
            MockCls.return_value = mock_resolver
            yield

    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.populate_agent_configs")
    @patch("agento.framework.consumer.prepare_run_dir")
    @patch("agento.framework.consumer.build_run_dir", return_value="/workspace/acme/dev/runs/1")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_uses_agent_view_provider_over_primary_token(
        self, mock_resolve, mock_build, mock_prepare, mock_populate,
        mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        sample_db_config, sample_consumer_config,
    ):
        mock_resolve.return_value = _make_runtime_with_agent_view(provider="codex", model="o3")
        mock_conn.return_value = MagicMock()

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._run_job(_make_job(agent_view_id=2))

        MockRunner.assert_called_once()
        assert MockRunner.call_args[0][0] == AgentProvider.CODEX
        assert MockRunner.call_args.kwargs["model_override"] == "o3"

    @patch("agento.framework.consumer.get_primary_token")
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_falls_back_to_primary_token_when_no_provider(
        self, mock_resolve, mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        mock_primary, sample_db_config, sample_consumer_config,
    ):
        mock_resolve.return_value = AgentViewRuntime()  # no provider
        mock_conn.return_value = MagicMock()

        primary = MagicMock()
        primary.agent_type = AgentProvider.CLAUDE
        mock_primary.return_value = primary

        mock_result = _make_claude_result()
        mock_workflow = MagicMock()
        mock_workflow.execute_job.return_value = mock_result
        mock_get_wf.return_value.return_value = mock_workflow
        mock_get_ch.return_value = MagicMock(name="jira")

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))
        consumer._run_job(_make_job())

        MockRunner.assert_called_once()
        assert MockRunner.call_args[0][0] == AgentProvider.CLAUDE

    @patch("agento.framework.consumer.get_primary_token", return_value=None)
    @patch("agento.framework.consumer.get_workflow_class")
    @patch("agento.framework.consumer.get_channel")
    @patch("agento.framework.consumer.create_runner")
    @patch("agento.framework.consumer.get_connection")
    @patch("agento.framework.consumer.resolve_agent_view_runtime")
    def test_raises_when_no_provider_and_no_primary_token(
        self, mock_resolve, mock_conn, MockRunner, mock_get_ch, mock_get_wf,
        mock_primary, sample_db_config, sample_consumer_config,
    ):
        mock_resolve.return_value = AgentViewRuntime()  # no provider
        mock_conn.return_value = MagicMock()

        consumer = Consumer(sample_db_config, sample_consumer_config, logging.getLogger("test"))

        with pytest.raises(RuntimeError, match="No agent_view/provider configured"):
            consumer._run_job(_make_job())
