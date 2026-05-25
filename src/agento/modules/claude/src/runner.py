from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.runner import TokenRunner
from agento.framework.runner import RunResult
from agento.modules.claude.src.output_parser import parse_claude_output

if TYPE_CHECKING:
    from agento.framework.agent_manager.models import Token


class TokenClaudeRunner(TokenRunner):
    """Unified Claude runner — handles both OAuth and subscription credentials."""

    @property
    def agent_type(self) -> AgentProvider:
        return AgentProvider.CLAUDE

    def _build_env(self, token: Token) -> dict[str, str]:
        if token.type == "anthropic_api_key":
            credentials = token.credentials or {}
            api_key = credentials.get("api_key")
            if not api_key:
                raise ValueError(
                    f"Token id={token.id} label={token.label!r} is typed "
                    "'anthropic_api_key' but credentials['api_key'] is missing or empty."
                )
            return {"ANTHROPIC_API_KEY": api_key}
        return {}

    def _build_command(self, prompt: str, model: str | None = None) -> list[str]:
        # .mcp.json is resolved relative to subprocess cwd (per-job artifacts dir)
        cmd = [
            "claude", "-p", prompt,
            "--dangerously-skip-permissions",
            "--mcp-config", ".mcp.json",
            "--strict-mcp-config",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _build_resume_command(self, session_id: str, model: str | None = None) -> list[str]:
        # .mcp.json is resolved relative to subprocess cwd (per-job artifacts dir)
        cmd = [
            "claude", "--resume", session_id,
            "-p", "Continue working from where you left off.",
            "--dangerously-skip-permissions",
            "--mcp-config", ".mcp.json",
            "--strict-mcp-config",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _parse_output(self, raw: str) -> RunResult:
        return parse_claude_output(raw, self.logger)

    def _try_parse_session_id(self, line: str) -> str | None:
        try:
            event = json.loads(line.strip())
            if isinstance(event, dict) and event.get("session_id"):
                return event["session_id"]
        except (json.JSONDecodeError, TypeError):
            pass
        return None
