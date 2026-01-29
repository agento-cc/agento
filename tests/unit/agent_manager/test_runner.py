from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.runner import Runner
from agento.modules.claude.src.runner import TokenClaudeRunner
from agento.modules.codex.src.runner import TokenCodexRunner


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


class TestTokenClaudeRunner:
    def test_agent_type(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner.agent_type == AgentProvider.CLAUDE

    def test_build_env_subscription(self):
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({"subscription_key": "sk-ant-api01-test"})
        assert env == {"ANTHROPIC_API_KEY": "sk-ant-api01-test"}

    def test_build_env_oauth(self):
        """OAuth mode: subscription_type set → empty env (CLI handles auth)."""
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({
            "subscription_key": "sk-ant-oat01-xyz",
            "subscription_type": "team",
        })
        assert env == {}

    def test_build_env_no_key(self):
        """No subscription_key at all → empty env."""
        runner = TokenClaudeRunner(dry_run=True)
        env = runner._build_env({"access_token": "oa-xyz"})
        assert env == {}

    def test_build_command(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world")
        assert cmd == ["claude", "-p", "Hello world", "--dangerously-skip-permissions", "--output-format", "json"]

    def test_build_command_with_model(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello world", model="claude-sonnet-4-20250514")
        assert cmd == [
            "claude", "-p", "Hello world",
            "--dangerously-skip-permissions", "--output-format", "json",
            "--model", "claude-sonnet-4-20250514",
        ]

    def test_build_command_no_model_when_none(self):
        runner = TokenClaudeRunner(dry_run=True)
        cmd = runner._build_command("Hello", model=None)
        assert "--model" not in cmd

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

    def test_parse_output_invalid_json(self):
        runner = TokenClaudeRunner(dry_run=True)
        result = runner._parse_output("not json")
        assert result.raw_output == "not json"
        assert result.input_tokens is None

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_run_executes_subprocess(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/claude_1.json"
        mock_read_creds.return_value = {"subscription_key": "sk-ant-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "ok",
                "usage": {"input_tokens": 200, "output_tokens": 100},
                "total_cost_usd": 0.01,
                "num_turns": 2,
                "duration_ms": 3000,
                "subtype": "success",
            }),
            stderr="",
        )

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)
        runner._resolve_token = MagicMock(return_value=None)
        runner._record_usage = MagicMock()

        result = runner.run("test prompt")

        assert result.input_tokens == 200
        assert result.output_tokens == 100
        assert result.agent_type == "claude"
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert call_args.kwargs["cwd"] == "/workspace"
        assert "ANTHROPIC_API_KEY" in call_args.kwargs["env"]

    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_run_raises_when_no_active_token(self, mock_resolve, agent_config):
        mock_resolve.return_value = None

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)

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
            "user\nczesc\ncodex\nCześć!\n"
            "tokens used\n6,374\nCześć!\n"
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

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_run_executes_subprocess(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/codex_1.json"
        mock_read_creds.return_value = {"subscription_key": "sk-openai-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="codex result output",
            stderr="",
        )

        runner = TokenCodexRunner(config=agent_config, dry_run=False)
        runner._resolve_token = MagicMock(return_value=None)
        runner._record_usage = MagicMock()

        result = runner.run("test prompt")

        assert result.raw_output == "codex result output"
        assert result.agent_type == "codex"
        call_args = mock_subprocess.call_args
        assert "OPENAI_API_KEY" in call_args.kwargs["env"]


class TestSubprocessTimeout:
    def test_timeout_passed_to_init(self):
        runner = TokenClaudeRunner(dry_run=True, timeout_seconds=900)
        assert runner.timeout_seconds == 900

    def test_default_timeout(self):
        runner = TokenClaudeRunner(dry_run=True)
        assert runner.timeout_seconds == 1200

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_timeout_passed_to_subprocess(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/claude_1.json"
        mock_read_creds.return_value = {"subscription_key": "sk-ant-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}),
            stderr="",
        )

        runner = TokenClaudeRunner(config=agent_config, dry_run=False, timeout_seconds=600)
        runner._resolve_token = MagicMock(return_value=None)
        runner._record_usage = MagicMock()

        runner.run("test")

        call_kwargs = mock_subprocess.call_args.kwargs
        assert call_kwargs["timeout"] == 600

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_timeout_expired_propagates(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/claude_1.json"
        mock_read_creds.return_value = {"subscription_key": "sk-ant-test"}
        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=600)

        runner = TokenClaudeRunner(config=agent_config, dry_run=False, timeout_seconds=600)
        runner._resolve_token = MagicMock(return_value=None)

        with pytest.raises(subprocess.TimeoutExpired):
            runner.run("test")


class TestCredentialsPath:
    """Verify that credentials_path takes precedence over symlink resolution."""

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_credentials_path_skips_symlink(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_read_creds.return_value = {"subscription_key": "sk-ant-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}),
            stderr="",
        )

        runner = TokenClaudeRunner(
            config=agent_config,
            dry_run=False,
            credentials_path="/etc/tokens/specific.json",
        )
        runner._resolve_token = MagicMock(return_value=None)
        runner._record_usage = MagicMock()

        runner.run("test")

        mock_resolve.assert_not_called()
        mock_read_creds.assert_called_once_with("/etc/tokens/specific.json")

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_falls_back_to_symlink_when_no_credentials_path(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/active_claude.json"
        mock_read_creds.return_value = {"subscription_key": "sk-ant-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}),
            stderr="",
        )

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)
        runner._resolve_token = MagicMock(return_value=None)
        runner._record_usage = MagicMock()

        runner.run("test")

        mock_resolve.assert_called_once()
        mock_read_creds.assert_called_once_with("/etc/tokens/active_claude.json")


class TestRecordUsageBestEffort:
    """Verify that usage recording failures don't crash the runner."""

    @patch("agento.framework.agent_manager.runner.subprocess.run")
    @patch("agento.framework.agent_manager.runner.read_credentials")
    @patch("agento.framework.agent_manager.runner.resolve_active_token")
    def test_continues_on_usage_recording_failure(self, mock_resolve, mock_read_creds, mock_subprocess, agent_config):
        mock_resolve.return_value = "/etc/tokens/claude_1.json"
        mock_read_creds.return_value = {"subscription_key": "sk-test"}
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}),
            stderr="",
        )

        runner = TokenClaudeRunner(config=agent_config, dry_run=False)

        # _resolve_token will fail because there's no DB — but run() should still return
        result = runner.run("test")

        assert result.input_tokens == 10
        assert result.output_tokens == 5
