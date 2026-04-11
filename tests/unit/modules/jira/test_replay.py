"""Tests for src.replay module."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.job_models import AgentType, Job, JobStatus
from agento.framework.replay import (
    build_replay_command,
)


def _make_job(**overrides) -> Job:
    defaults = dict(
        id=42,
        schedule_id=None,
        type=AgentType.CRON,
        source="jira",
        agent_view_id=None,
        priority=50,
        reference_id="AI-1",
        agent_type="claude",
        model="claude-sonnet-4-20250514",
        input_tokens=1500,
        output_tokens=800,
        prompt="Zadanie cykliczne (jira) AI-1. Postępuj krok po kroku:",
        output='{"result": "ok"}',
        context=None,
        idempotency_key="jira:cron:AI-1:20260220_0800",
        status=JobStatus.SUCCESS,
        attempt=1,
        max_attempts=3,
        scheduled_after=datetime(2026, 2, 20, 8, 0),
        started_at=datetime(2026, 2, 20, 8, 0, 5),
        finished_at=datetime(2026, 2, 20, 8, 1, 0),
        result_summary="subtype=success turns=3",
        error_message=None,
        error_class=None,
        pid=None,
        session_id=None,
        created_at=datetime(2026, 2, 20, 7, 59),
        updated_at=datetime(2026, 2, 20, 8, 1, 0),
    )
    defaults.update(overrides)
    return Job(**defaults)


def _mock_runner_for(agent_type: str):
    """Create a mock runner that builds commands like the real runner."""
    runner = MagicMock()
    if agent_type == "claude":
        def build_cmd(prompt, *, model=None):
            cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"]
            if model:
                cmd.extend(["--model", model])
            return cmd
    elif agent_type == "codex":
        def build_cmd(prompt, *, model=None):
            cmd = ["codex", "exec", prompt, "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]
            if model:
                cmd.extend(["--model", model])
            return cmd
    else:
        raise ValueError(f"Unknown agent type in test: {agent_type}")
    runner.build_command = build_cmd
    return runner


@pytest.fixture(autouse=True)
def _mock_create_runner():
    """Mock create_runner so replay tests don't need bootstrap."""
    def factory(provider, **kwargs):
        return _mock_runner_for(provider.value)

    with patch("agento.framework.replay.create_runner", side_effect=factory):
        yield


class TestBuildReplayCommand:
    def test_claude_command_structure(self):
        job = _make_job(agent_type="claude", model="claude-sonnet-4-20250514")
        rc = build_replay_command(job)

        assert rc.args[0] == "claude"
        assert rc.args[1] == "-p"
        assert rc.args[2] == job.prompt
        assert "--dangerously-skip-permissions" in rc.args
        assert "--output-format" in rc.args
        assert "stream-json" in rc.args
        assert "--model" in rc.args
        assert "claude-sonnet-4-20250514" in rc.args

    def test_claude_command_no_model(self):
        job = _make_job(agent_type="claude", model=None)
        rc = build_replay_command(job)

        assert "--model" not in rc.args
        assert rc.model is None

    def test_codex_command_structure(self):
        job = _make_job(agent_type="codex", model="o3")
        rc = build_replay_command(job)

        assert rc.args[0] == "codex"
        assert rc.args[1] == "exec"
        assert rc.args[2] == job.prompt
        assert "--dangerously-bypass-approvals-and-sandbox" in rc.args
        assert "--model" in rc.args
        assert "o3" in rc.args

    def test_codex_command_no_model(self):
        job = _make_job(agent_type="codex", model=None)
        rc = build_replay_command(job)

        assert "--model" not in rc.args

    def test_no_prompt_raises(self):
        job = _make_job(prompt=None)
        with pytest.raises(ValueError, match="no stored prompt"):
            build_replay_command(job)

    def test_no_agent_type_raises(self):
        job = _make_job(agent_type=None)
        with pytest.raises(ValueError, match="no agent_type"):
            build_replay_command(job)

    def test_unknown_agent_type_raises(self):
        job = _make_job(agent_type="unknown_agent")
        with pytest.raises(ValueError, match="Unknown agent type"):
            build_replay_command(job)

    def test_model_override(self):
        job = _make_job(agent_type="claude", model="claude-sonnet-4-20250514")
        rc = build_replay_command(job, model_override="claude-opus-4-20250514")

        assert "claude-opus-4-20250514" in rc.args
        assert "claude-sonnet-4-20250514" not in rc.args
        assert rc.model == "claude-opus-4-20250514"

    def test_agent_type_override_to_codex(self):
        job = _make_job(agent_type="claude", model="claude-sonnet-4-20250514")
        rc = build_replay_command(job, agent_type_override="codex", model_override="o3")

        assert rc.args[0] == "codex"
        assert rc.agent_type == "codex"
        assert "o3" in rc.args

    def test_agent_type_override_to_claude(self):
        job = _make_job(agent_type="codex", model="o3")
        rc = build_replay_command(job, agent_type_override="claude", model_override="claude-sonnet-4-20250514")

        assert rc.args[0] == "claude"
        assert rc.agent_type == "claude"
        assert "claude-sonnet-4-20250514" in rc.args

    def test_unknown_agent_type_override_raises(self):
        job = _make_job(agent_type="claude")
        with pytest.raises(ValueError, match="Unknown agent type"):
            build_replay_command(job, agent_type_override="unknown_provider")

    def test_replay_command_metadata(self):
        job = _make_job(agent_type="claude", model="claude-sonnet-4-20250514")
        rc = build_replay_command(job)

        assert rc.agent_type == "claude"
        assert rc.model == "claude-sonnet-4-20250514"
        assert rc.prompt == job.prompt
        assert rc.job is job

    def test_shell_command_is_safe(self):
        job = _make_job(prompt="prompt with 'single quotes' and spaces")
        rc = build_replay_command(job)
        shell = rc.shell_command

        assert isinstance(shell, str)
        assert "claude" in shell

    def test_shell_command_contains_prompt(self):
        job = _make_job(agent_type="claude", prompt="my test prompt")
        rc = build_replay_command(job)

        assert "my test prompt" in rc.shell_command
