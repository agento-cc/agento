from __future__ import annotations

import re
import subprocess

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.runner import TokenRunner
from agento.framework.runner import RunResult


class TokenCodexRunner(TokenRunner):
    """Token-managed Codex runner using a subscription key."""

    @property
    def agent_type(self) -> AgentProvider:
        return AgentProvider.CODEX

    def _build_env(self, credentials: dict) -> dict[str, str]:
        # OAuth — let Codex CLI use its own auth from real HOME
        if credentials.get("refresh_token"):
            return {}
        # API key — pass directly
        return {"OPENAI_API_KEY": credentials["subscription_key"]}

    def _build_command(self, prompt: str, model: str | None = None) -> list[str]:
        cmd = ["codex", "exec", prompt, "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _build_resume_command(self, session_id: str, model: str | None = None) -> list[str]:
        # Non-interactive resume: `codex exec resume <id> <prompt>` (not `codex resume`, which needs a TTY).
        cmd = [
            "codex", "exec", "resume", session_id,
            "Continue working from where you left off.",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _try_parse_session_id(self, line: str) -> str | None:
        stripped = line.strip()
        if stripped.startswith("session id:"):
            return stripped.split(":", 1)[1].strip() or None
        return None

    def _extract_raw(self, proc: subprocess.CompletedProcess) -> str:
        """Codex puts the response on stdout and header/stats on stderr.

        Combine both so ``_parse_output`` can extract model, session id,
        and token count from stderr while preserving the response as raw_output.
        """
        parts = [p for p in (proc.stderr, proc.stdout) if p]
        return "\n".join(parts) if parts else ""

    def _parse_output(self, raw: str) -> RunResult:
        """Parse Codex CLI structured text output.

        Extracts model, session id, and token count from the header/footer.
        Falls back gracefully if the format is unexpected.
        """
        result = RunResult(raw_output=raw)
        try:
            self._parse_header(raw, result)
            self._parse_tokens(raw, result)
        except Exception:
            self.logger.warning(f"Failed to parse Codex output: {raw[:200]}")
        return result

    @staticmethod
    def _parse_header(raw: str, result: RunResult) -> None:
        """Extract model and session id from the header block between -------- markers."""
        for line in raw.splitlines():
            if line.startswith("model:"):
                result.model = line.split(":", 1)[1].strip()
            elif line.startswith("session id:"):
                result.subtype = line.split(":", 1)[1].strip()

    @staticmethod
    def _parse_tokens(raw: str, result: RunResult) -> None:
        """Extract total tokens from 'tokens used\\n<number>' pattern."""
        match = re.search(r"tokens used\n([\d,]+)", raw)
        if match:
            result.input_tokens = int(match.group(1).replace(",", ""))
