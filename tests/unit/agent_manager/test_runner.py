from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.errors import AuthenticationError
from agento.framework.agent_manager.models import AgentProvider, Token, TokenStatus
from agento.framework.runner import Runner
from agento.modules.claude.src.runner import TokenClaudeRunner
from agento.modules.codex.src.runner import TokenCodexRunner

_EPOCH = datetime(2000, 1, 1)


def _make_token(credentials: dict, agent_type: AgentProvider = AgentProvider.CLAUDE) -> Token:
    return Token(
        id=1,
        agent_type=agent_type,
        type="oauth",
        label="test",
        credentials=credentials,
        model=None,
        token_limit=0,
        enabled=True,
        status=TokenStatus.OK,
        priority=0,
        error_msg=None,
        expires_at=None,
        used_at=None,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    )

_CODEX_FIXTURES = Path(__file__).parents[2] / "fixtures" / "codex"


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
    def _make_token(self, type_: str, credentials: dict) -> Token:
        return Token(
            id=1,
            agent_type=AgentProvider.CLAUDE,
            type=type_,
            label="test",
            credentials=credentials,
            model=None,
            token_limit=0,
            enabled=True,
            status=TokenStatus.OK,
            priority=0,
            error_msg=None,
            expires_at=None,
            used_at=None,
            created_at=_EPOCH,
            updated_at=_EPOCH,
        )

    def test_agent_type(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner.agent_type == AgentProvider.CLAUDE

    def test_build_env_oauth_returns_empty(self):
        runner = TokenClaudeRunner(dry_run=True)
        token = self._make_token(
            type_="oauth",
            credentials={"subscription_key": "x", "refresh_token": "y"},
        )
        assert runner._build_env(token) == {}

    def test_build_env_anthropic_api_key(self):
        runner = TokenClaudeRunner(dry_run=True)
        token = self._make_token(
            type_="anthropic_api_key",
            credentials={"api_key": "sk-ant-XYZ"},
        )
        assert runner._build_env(token) == {"ANTHROPIC_API_KEY": "sk-ant-XYZ"}

    def test_build_env_anthropic_api_key_missing_value_raises(self):
        runner = TokenClaudeRunner(dry_run=True)
        token = self._make_token(
            type_="anthropic_api_key",
            credentials={},  # type says api_key but credentials are empty
        )
        with pytest.raises(ValueError, match="anthropic_api_key"):
            runner._build_env(token)

    def test_build_command(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert cmd == [
            "claude", "-p", "Hello world",
            "--dangerously-skip-permissions",
            "--mcp-config", ".mcp.json",
            "--strict-mcp-config",
            "--output-format", "stream-json",
            "--verbose",
        ]

    def test_build_command_with_model(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world", model="claude-sonnet-4-20250514")
        assert cmd == [
            "claude", "-p", "Hello world",
            "--dangerously-skip-permissions",
            "--mcp-config", ".mcp.json",
            "--strict-mcp-config",
            "--output-format", "stream-json",
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
            "--mcp-config", ".mcp.json",
            "--strict-mcp-config",
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
        runner._resolve_token_from_pool = MagicMock(return_value=None)

        with pytest.raises(RuntimeError, match="No healthy token"):
            runner.run("test prompt")


class TestTokenCodexRunner:
    def _make_token(self, type_: str, credentials: dict) -> Token:
        return Token(
            id=1,
            agent_type=AgentProvider.CODEX,
            type=type_,
            label="test",
            credentials=credentials,
            model=None,
            token_limit=0,
            enabled=True,
            status=TokenStatus.OK,
            priority=0,
            error_msg=None,
            expires_at=None,
            used_at=None,
            created_at=_EPOCH,
            updated_at=_EPOCH,
        )

    def test_agent_type(self):
        runner = TokenCodexRunner(dry_run=True)
        assert runner.agent_type == AgentProvider.CODEX

    def test_build_env_oauth_returns_empty(self):
        runner = TokenCodexRunner(dry_run=True)
        token = self._make_token(
            type_="oauth",
            credentials={
                "subscription_key": "acc-x",
                "refresh_token": "rt",
                "raw_auth": {"tokens": {"access_token": "acc-x"}},
            },
        )
        assert runner._build_env(token) == {}

    def test_build_env_openai_api_key(self):
        runner = TokenCodexRunner(dry_run=True)
        token = self._make_token(
            type_="openai_api_key",
            credentials={"api_key": "sk-X"},
        )
        assert runner._build_env(token) == {"OPENAI_API_KEY": "sk-X"}

    def test_build_env_codex_access_token_returns_empty(self):
        runner = TokenCodexRunner(dry_run=True)
        token = self._make_token(
            type_="codex_access_token",
            credentials={"access_token": "eyJ.payload.sig", "expires_at": 9999999999},
        )
        assert runner._build_env(token) == {}

    def test_build_command(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert cmd == [
            "codex", "exec", "Hello world",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]

    def test_build_command_with_model(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_command("Hello world", model="o3")
        assert cmd == [
            "codex", "exec", "Hello world",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--model", "o3",
        ]

    def test_build_resume_command(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-456")
        assert cmd == [
            "codex", "exec", "resume", "sess-456",
            "Continue working from where you left off.",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]

    def test_build_resume_command_with_model(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-456", model="o3")
        assert "--model" in cmd
        assert "o3" in cmd

    def test_run_executes_subprocess(self, agent_config):
        runner = TokenCodexRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-openai-test"},
        )
        runner._record_usage = MagicMock()
        stream = (
            '{"type":"thread.started","thread_id":"sess-x"}\n'
            '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"codex result output"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}\n'
        )
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream),
        )

        result = runner.run("test prompt")

        assert "codex result output" in result.raw_output
        assert result.agent_type == "codex"


class TestTokenCodexRunnerJsonOutput:
    """NDJSON-mode parsing (codex exec --json).

    These cover the post-migration contract: stdout carries newline-delimited
    JSON events; auth failure is signalled only by a structured ``turn.failed``
    event whose ``error.message`` matches an anchored auth phrase. The bare
    substring ``"401"`` anywhere in MCP payloads (e.g. order numbers) must NOT
    trigger AuthenticationError — that was the production bug being fixed.
    """

    def test_build_command_includes_json_flag(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert "--json" in cmd

    def test_build_resume_command_includes_json_flag(self):
        runner = TokenCodexRunner(dry_run=True)
        cmd = runner._build_resume_command("sess-456")
        assert "--json" in cmd

    def test_try_parse_session_id_from_thread_started(self):
        runner = TokenCodexRunner(dry_run=True)
        line = '{"type":"thread.started","thread_id":"019e585e-aaa-bbb-ccc"}'
        assert runner._try_parse_session_id(line) == "019e585e-aaa-bbb-ccc"

    def test_try_parse_session_id_ignores_other_events(self):
        runner = TokenCodexRunner(dry_run=True)
        assert runner._try_parse_session_id('{"type":"turn.started"}') is None
        assert runner._try_parse_session_id('{"type":"item.completed","item":{}}') is None

    def test_try_parse_session_id_ignores_non_json(self):
        runner = TokenCodexRunner(dry_run=True)
        assert runner._try_parse_session_id("not json") is None
        assert runner._try_parse_session_id("") is None

    def test_parse_output_simple_success(self):
        raw = (_CODEX_FIXTURES / "success_simple.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)

        assert result.subtype == "019e585e-526a-7943-b543-160dddddc56e"
        assert result.input_tokens == 1234
        # output_tokens covers visible reply + reasoning tokens
        assert result.output_tokens == 50
        assert "Hello! I'm ready to help." in result.raw_output

    def test_parse_output_does_NOT_raise_on_substring_401_in_mcp_payload(self):
        """Regression guard for the production token-poisoning bug.

        The string ``401`` appears inside an mcp_tool_call payload (order id
        substring). The legacy text parser scanned the whole blob and
        false-positive'd. The JSON parser must only inspect structured
        ``turn.failed`` events.
        """
        raw = (_CODEX_FIXTURES / "mcp_payload_with_401_substring.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)  # must NOT raise

        assert result.subtype == "019e585e-ab85-7cb1-bdc5-33a5877cb247"
        assert result.input_tokens == 101854
        assert "353043085362789" in result.raw_output

    def test_parse_output_raises_authentication_error_on_turn_failed_401(self):
        raw = (_CODEX_FIXTURES / "auth_failure.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        with pytest.raises(AuthenticationError) as exc_info:
            runner._parse_output(raw)

        assert "401" in str(exc_info.value)

    def test_parse_output_no_turn_completed_returns_partial_result(self):
        """If codex dies mid-stream (no turn.completed), parser still extracts
        what's available without raising. Token usage is None; raw_output has
        whatever agent_message text was emitted."""
        raw = (_CODEX_FIXTURES / "no_turn_completed.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)

        assert result.subtype == "019e5862-b829-7552-8007-11e34c456a93"
        assert result.input_tokens is None
        assert result.output_tokens is None
        assert "Toolbox not reachable" in result.raw_output

    def test_parse_output_only_thread_started(self):
        """Process killed right after thread.started — we still get the session
        id (so the consumer can resume), no tokens, empty agent text."""
        raw = (_CODEX_FIXTURES / "thread_started_only.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)

        assert result.subtype == "019e5872-aaaa-bbbb-cccc-ddddeeeeffff"
        assert result.input_tokens is None
        assert result.raw_output == ""

    def test_parse_output_skips_malformed_lines(self):
        """Defensive against partial flushes — a non-JSON line in the stream
        must be skipped, not crash the parser."""
        raw = (
            '{"type":"thread.started","thread_id":"sess-x"}\n'
            'GARBAGE LINE NOT JSON\n'
            '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"hi"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}\n'
        )
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)

        assert result.subtype == "sess-x"
        assert result.input_tokens == 10
        assert result.output_tokens == 2
        assert "hi" in result.raw_output

    def test_parse_output_real_success_with_mcp_calls(self):
        """Real captured sample — order lookup w/ multiple toolbox MCP calls."""
        raw = (_CODEX_FIXTURES / "real_success_with_mcp.ndjson").read_text()
        runner = TokenCodexRunner(dry_run=True)

        result = runner._parse_output(raw)

        assert result.subtype == "019e585e-ab85-7cb1-bdc5-33a5877cb247"
        # turn.completed.usage.input_tokens
        assert result.input_tokens == 101854
        # output_tokens (1904) + reasoning_output_tokens (833)
        assert result.output_tokens == 1904 + 833
        # raw_output is the concatenated agent_message text(s) from item.completed
        assert "353043085362789" in result.raw_output

    def test_extract_raw_uses_stdout_only_not_stderr(self):
        """The new parser MUST NOT concatenate stderr. Codex log lines on
        stderr (Rust tracing output) contain '401' substrings that would
        false-positive substring-based auth detection — we sidestep that
        entirely by ignoring stderr."""
        runner = TokenCodexRunner(dry_run=True)
        proc = _make_completed_process(
            stdout='{"type":"thread.started","thread_id":"s"}\n',
            stderr="ERROR codex_api: HTTP error: 401 Unauthorized\n",
        )

        raw = runner._extract_raw(proc)

        assert "401" not in raw
        assert "thread.started" in raw


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
    """Verify that credentials_override takes precedence over DB pool resolution."""

    def test_override_skips_db(self, agent_config):
        stream_output = '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_override={"subscription_key": "sk-override"},
        )
        runner._resolve_token_from_pool = MagicMock()
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        runner.run("test")

        runner._resolve_token_from_pool.assert_not_called()

    def test_falls_back_to_db_when_no_override(self, agent_config):
        from .conftest import make_token

        pool_token = make_token(
            id=1,
            label="p",
            credentials={"subscription_key": "sk-primary"},
            token_limit=0,
        )
        stream_output = '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)
        runner._resolve_token_from_pool = MagicMock(return_value=pool_token)
        runner._record_usage = MagicMock()
        runner._execute_process = MagicMock(
            return_value=_make_completed_process(stdout=stream_output),
        )

        runner.run("test")

        runner._resolve_token_from_pool.assert_called_once()


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
