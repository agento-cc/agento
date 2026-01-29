from __future__ import annotations

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.runner import TokenRunner
from agento.framework.runner import RunResult
from agento.modules.claude.src.output_parser import parse_claude_output


class TokenClaudeRunner(TokenRunner):
    """Unified Claude runner — handles both OAuth and subscription credentials."""

    @property
    def agent_type(self) -> AgentProvider:
        return AgentProvider.CLAUDE

    def _build_env(self, credentials: dict) -> dict[str, str]:
        # OAuth tokens (subscription_type set) — CLI handles auth internally
        if credentials.get("subscription_type"):
            return {}
        if "subscription_key" in credentials:
            return {"ANTHROPIC_API_KEY": credentials["subscription_key"]}
        return {}

    def _build_command(self, prompt: str, model: str | None = None) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--dangerously-skip-permissions",
            "--output-format", "json",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _parse_output(self, raw: str) -> RunResult:
        return parse_claude_output(raw, self.logger)
