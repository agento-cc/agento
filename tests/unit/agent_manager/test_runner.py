from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.runner import Runner
from agento.modules.claude.src.runner import TokenClaudeRunner
from agento.modules.codex.src.runner import TokenCodexRunner


def _make_completed_process(
    returncode: int = 0, stdout: str = "", stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["test"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


class TestRunnerProtocolCompliance:
    """Verify that TokenClaudeRunner and TokenCodexRunner satisfy the Runner Protocol."""

    def test_token_claude_runner_is_runner(self):
        assert issubclass(TokenClaudeRunner, Runner) or isinstance(
            TokenClaudeRunner(dry_run=True), Runner
        )

    def test_token_codex_runner_is_runner(self):
        assert issubclass(TokenCodexRunner, Runner) or isinstance(
            TokenCodexRunner(dry_run=True), Runner
        )


class TestTokenRunnerDryRun:
    def test_claude_dry_run(self):
        runner = TokenClaudeRunner(dry_run=True)

        result = runner.run("test prompt")

        assert result.raw_output == "[DRY RUN] skipped"

    def test_codex_dry_run(self):
        runner = TokenCodexRunner(dry_run=True)

        result = runner.run("test prompt")

        assert result.raw_output == "[DRY RUN] skipped"

    def test_claude_resume_dry_run(self):
        runner = TokenClaudeRunner(dry_run=True)
        result = runner.resume("session-abc")
        assert result.raw_output == "[DRY RUN] skipped"

    def test_codex_resume_dry_run(self):
        runner = TokenCodexRunner(dry_run=True)
        result = runner.resume("session-abc")
        assert result.raw_output == "[DRY RUN] skipped"


class TestTokenClaudeRunner:
    def test_agent_type(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner.agent_type == AgentProvider.CLAUDE

    def test_build_env_subscription(self):
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({"subscription_key": "sk-ant-api01-test"})
        assert env == {"ANTHROPIC_API_KEY": "sk-ant-api01-test"}

    def test_build_env_oauth(self):
        """OAuth mode: subscription_type set -> empty env (CLI handles auth)."""
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({
            "subscription_key": "sk-ant-oat01-xyz",
            "subscription_type": "team",
        })
        assert env == {}

    def test_build_env_no_key(self):
        """No subscription_key at all -> empty env."""
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({"access_token": "oa-xyz"})
        assert env == {}

    def test_build_command(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert cmd == [
            "claude", "-p", "Hello world",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
        ]

    def test_build_command_with_model(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world", model="claude-sonnet-4-20250514")
        assert cmd == [
            "claude", "-p", "Hello world",
            "--dangerously-skip-permissions", "--output-format", "stream-json",
            "--verbose",
            "--model", "claude-sonnet-4-20250514",
        ]

    def test_build_command_no_model_when_none(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello", model=None)
        assert "--model" not in cmd

    def test_build_resume_command(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-123")
        assert cmd == [
            "claude", "--resume", "sess-123",
            "-p", "Continue working from where you left off.",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
        ]

    def test_build_resume_command_with_model(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-123", model="claude-sonnet-4-20250514")
        assert "--model" in cmd
        assert "claude-sonnet-4-20250514" in cmd

    def test_parse_output_valid_json(self):
        runner = TokenClaudeRunner(dry_run=True)
        data = {
            "result": "done",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "total_cost_usd": 0.005,
            "num_turns": 1,
            "duration_ms": 2000,
            "subtype": "success",
        }
        result = runner._parse_output(json.dumps(data))
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost_usd == 0.005

    def test_parse_output_stream_json(self):
        runner = TokenClaudeRunner(dry_run=True)
        raw = (
            '{"type": "init", "session_id": "sess-abc"}\n'
            '{"type": "assistant", "message": "hello"}\n'
            '{"type": "result", "result": "done", "usage": {"input_tokens": 200, "output_tokens": 100}, '
            '"total_cost_usd": 0.01, "num_turns": 2, "duration_ms": 3000, "session_id": "sess-abc"}\n'
        )
        result = runner._parse_output(raw)
        assert result.input_tokens == 200
        assert result.output_tokens == 100
        assert result.subtype == "sess-abc"

    def test_parse_output_invalid_json(self):
        runner = TokenClaudeRunner(dry_run=True)
        result = runner._parse_output("not json")
        assert result.raw_output == "not json"
        assert result.input_tokens is None

    def test_try_parse_session_id(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner._try_parse_session_id('{"session_id": "sess-abc"}') == "sess-abc"
        assert runner._try_parse_session_id('{"type": "init"}') is None
        assert runner._try_parse_session_id("not json") is None

    def test_run_executes_subprocess(self, agent_config):
        stream_output = (
            '{"type": "result", "result": "ok", "usage": {"input_tokens": 200, "output_tokens": 100}, '
            '"total_cost_usd": 0.01, "num_turns": 2, "duration_ms": 3000, "session_id": "sess-1"}\n'
        )

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-ant-test"},
        )
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        result = runner.run("test prompt")

        assert result.input_tokens == 200
        assert result.output_tokens == 100
        assert result.agent_type == "claude"
        runner._execute_process.assert_called_once()

    def test_run_raises_when_no_active_token(self, agent_config):
        runner = TokenClaudeRunner(config=agent_config, dry_run=False)
        runner._resolve_primary_token = MagicMock(return_value=None)

        with pytest.raises(RuntimeError, match="No active token"):
            runner.run("test prompt")


class TestTokenCodexRunner:
    def test_agent_type(self):
        runner = TokenCodexRunner(dry_run=True)
        assert runner.agent_type == AgentProvider.CODEX

    def test_build_env(self):
        runner = TokenCodexRunner(dry_run=True)
        env = runner._build_env({"subscription_key": "sk-openai-test"})
        assert env == {"OPENAI_API_KEY": "sk-openai-test"}

    def test_build_command(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert cmd == ["codex", "exec", "Hello world", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]

    def test_build_command_with_model(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_command("Hello world", model="o3")
        assert cmd == ["codex", "exec", "Hello world", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "--model", "o3"]

    def test_build_resume_command(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-456")
        assert cmd == [
            "codex", "exec", "resume", "sess-456",
            "Continue working from where you left off.",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]

    def test_build_resume_command_with_model(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-456", model="o3")
        assert "--model" in cmd
        assert "o3" in cmd

    def test_try_parse_session_id(self):
        runner = TokenCodexRunner(dry_run=True)
        assert runner._try_parse_session_id("session id: abc-123\n") == "abc-123"
        assert runner._try_parse_session_id("model: o3\n") is None
        assert runner._try_parse_session_id("session id:\n") is None

    def test_parse_output_returns_raw(self):
        runner = TokenCodexRunner(dry_run=True)
        result = runner._parse_output("some codex output")
        assert result.raw_output == "some codex output"
        assert result.input_tokens is None

    def test_parse_output_extracts_header(self):
        raw = (
            "OpenAI Codex v0.45.0 (research preview)\n"
            "--------\n"
            "workdir: /workspace\n"
            "model: gpt-5.2-codex\n"
            "provider: openai\n"
            "approval: never\n"
            "sandbox: read-only\n"
            "session id: 019cbcfa-837a-7130-b776-15ac3d39b1ad\n"
            "--------\n"
            "user\nczesc\ncodex\nCzesc!\n"
            "tokens used\n6,374\nCzesc!\n"
        )
        runner = TokenCodexRunner(dry_run=True)
        result = runner._parse_output(raw)

        assert result.model == "gpt-5.2-codex"
        assert result.subtype == "019cbcfa-837a-7130-b776-15ac3d39b1ad"
        assert result.input_tokens == 6374
        assert result.raw_output == raw

    def test_parse_output_no_tokens(self):
        raw = "model: o3\nsession id: abc-123\nsome output\n"
        runner = TokenCodexRunner(dry_run=True)
        result = runner._parse_output(raw)

        assert result.model == "o3"
        assert result.subtype == "abc-123"
        assert result.input_tokens is None

    def test_parse_output_fallback_on_garbage(self):
        runner = TokenCodexRunner(dry_run=True)
        result = runner._parse_output("totally unexpected output")
        assert result.raw_output == "totally unexpected output"
        assert result.model is None
        assert result.input_tokens is None

    def test_run_executes_subprocess(self, agent_config):
        runner = TokenCodexRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-openai-test"},
        )
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout="codex result output"),
        )

        result = runner.run("test prompt")

        assert result.raw_output == "codex result output"
        assert result.agent_type == "codex"


class TestSubprocessTimeout:
    def test_timeout_passed_to_init(self):
        runner = TokenClaudeRunner(dry_run=True, timeout_seconds=900)
        assert runner.timeout_seconds == 900

    def test_default_timeout(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner.timeout_seconds == 1200

    def test_timeout_expired_propagates(self, agent_config):
        exc = subprocess.TimeoutExpired(cmd="claude", timeout=600)
        exc.session_id = None  # type: ignore[attr-defined]

        runner = TokenClaudeRunner(
            config=agent_config, dry_run=False, timeout_seconds=600,
            credentials_override={"subscription_key": "sk-ant-test"},
        )
        runner._execute_process = MagicMock(side_effect=exc)

        with pytest.raises(subprocess.TimeoutExpired):
            runner.run("test")

    def test_timeout_with_session_id(self, agent_config):
        exc = subprocess.TimeoutExpired(cmd="claude", timeout=600)
        exc.session_id = "sess-timeout-abc"  # type: ignore[attr-defined]

        runner = TokenClaudeRunner(
            config=agent_config, dry_run=False, timeout_seconds=600,
            credentials_override={"subscription_key": "sk-ant-test"},
        )
        runner._execute_process = MagicMock(side_effect=exc)

        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            runner.run("test")

        assert exc_info.value.session_id == "sess-timeout-abc"  # type: ignore[attr-defined]


class TestCredentialsOverride:
    """Verify that credentials_override takes precedence over DB primary-token resolution."""

    def test_override_skips_db(self, agent_config):
        stream_output = '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-override"},
        )
        runner._resolve_primary_token = MagicMock()
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        runner.run("test")

        runner._resolve_primary_token.assert_not_called()

    def test_falls_back_to_db_when_no_override(self, agent_config):
        from datetime import UTC, datetime

        from agento.framework.agent_manager.models import AgentProvider, Token

        primary = Token(
            id=1, agent_type=AgentProvider.CLAUDE, label="p", credentials={"subscription_key": "sk-primary"},
            model=None, is_primary=True, token_limit=0, enabled=True,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        stream_output = '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)
        runner._resolve_primary_token = MagicMock(return_value=primary)
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        runner.run("test")

        runner._resolve_primary_token.assert_called_once()


class TestRecordUsageBestEffort:
    """Verify that usage recording failures don't crash the runner."""

    def test_continues_on_usage_recording_failure(self, agent_config):
        stream_output = '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-test"},
        )
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        # _record_usage silently swallows errors (no DB in test env) — run() should still return
        result = runner.run("test")

        assert result.input_tokens == 10
        assert result.output_tokens == 5


class TestPidAndSessionCallbacks:
    """Verify PID and session_id callbacks are invoked during _execute_process."""

    def test_pid_callback_invoked(self):
        runner = TokenClaudeRunner(dry_run=True)
        pids = []
        runner.pid_callback = lambda pid: pids.append(pid)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0

        with patch("agento.framework.agent_manager.runner.subprocess.Popen", return_value=mock_proc):
            runner._execute_process(["echo", "test"], {})

        assert pids == [12345]

    def test_session_id_callback_invoked(self):
        runner = TokenClaudeRunner(dry_run=True)
        session_ids = []
        runner.session_id_callback = lambda sid: session_ids.append(sid)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.stdout = iter(['{"session_id": "sess-abc"}\n', '{"type": "result"}\n'])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0

        with patch("agento.framework.agent_manager.runner.subprocess.Popen", return_value=mock_proc):
            runner._execute_process(["echo", "test"], {})

        assert session_ids == ["sess-abc"]


class TestResumeMethod:
    """Verify resume() calls _build_resume_command and delegates to _execute_and_parse."""

    def test_resume_calls_resume_command(self, agent_config):
        stream_output = (
            '{"type": "result", "result": "ok", "usage": {"input_tokens": 50, "output_tokens": 30}, '
            '"session_id": "sess-resumed"}\n'
        )

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-ant-test"},
        )
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        result = runner.resume("sess-original", model="claude-sonnet-4-20250514")

        assert result.input_tokens == 50
        assert result.agent_type == "claude"

        # Verify the command passed to _execute_process contains --resume
        call_args = runner._execute_process.call_args[0][0]
        assert "--resume" in call_args
        assert "sess-original" in call_args
