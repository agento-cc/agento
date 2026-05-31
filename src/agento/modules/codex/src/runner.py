from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

from agento.framework.agent_manager.errors import AuthenticationError
from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.runner import TokenRunner
from agento.framework.runner import RunResult

if TYPE_CHECKING:
    from agento.framework.agent_manager.models import Token

# Anchored auth phrases checked ONLY against turn.failed.error.message in the
# NDJSON stream. Never matched against raw stdout/stderr — that's the bug we're
# fixing (substring "401" in MCP payload order numbers used to poison tokens).
_AUTH_PHRASE_RE = re.compile(
    r"\b(401\s+Unauthorized|invalid[_ ]api[_ ]key|"
    r"please\s+(sign|log)\s+in|not\s+authenticated|"
    r"authentication\s+failed|missing\s+bearer)\b",
    re.IGNORECASE,
)


class TokenCodexRunner(TokenRunner):
    """Token-managed Codex runner using a subscription key."""

    @property
    def agent_type(self) -> AgentProvider:
        return AgentProvider.CODEX

    def _build_env(self, token: Token) -> dict[str, str]:
        from agento.framework.config_writer import get_config_writer
        return get_config_writer(self.agent_type).credential_env(token)

    def _build_command(self, prompt: str, model: str | None = None) -> list[str]:
        cmd = [
            "codex", "exec", prompt,
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _build_resume_command(self, session_id: str, model: str | None = None) -> list[str]:
        # Non-interactive resume: `codex exec resume <id> <prompt>` (not `codex resume`, which needs a TTY).
        cmd = [
            "codex", "exec", "resume", session_id,
            "Continue working from where you left off.",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd

    def _try_parse_session_id(self, line: str) -> str | None:
        """Streaming hook: extract thread_id from the first ``thread.started``
        event so the consumer can resume even if the process is killed."""
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(ev, dict) and ev.get("type") == "thread.started":
            return ev.get("thread_id") or None
        return None

    def _extract_raw(self, proc: subprocess.CompletedProcess) -> str:
        """Codex --json emits NDJSON on stdout. Stderr (Rust tracing output)
        is deliberately ignored — it can contain '401' substrings from log
        lines that would false-positive substring-based scans. The base
        runner still preserves stderr in its own logs."""
        return proc.stdout or ""

    def _parse_output(self, raw: str) -> RunResult:
        """Parse codex exec --json NDJSON stdout.

        Raises ``AuthenticationError`` only when a structured ``turn.failed``
        event carries an anchored auth phrase. Any other failure path
        (non-zero exit, missing turn.completed, malformed lines) returns a
        best-effort ``RunResult`` and lets the consumer retry without
        poisoning the token.
        """
        events = _parse_ndjson(raw)

        if (msg := _detect_auth_error(events)) is not None:
            raise AuthenticationError(f"Codex CLI auth error: {msg[:500]}")

        result = RunResult(raw_output=_extract_agent_text(events))
        _populate_session(events, result)
        _populate_usage(events, result)
        return result


def _parse_ndjson(raw: str) -> list[dict]:
    events: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def _detect_auth_error(events: list[dict]) -> str | None:
    for ev in events:
        if ev.get("type") != "turn.failed":
            continue
        err = ev.get("error") or {}
        msg = err.get("message", "") if isinstance(err, dict) else ""
        if msg and _AUTH_PHRASE_RE.search(msg):
            return msg
    return None


def _extract_agent_text(events: list[dict]) -> str:
    parts: list[str] = []
    for ev in events:
        if ev.get("type") != "item.completed":
            continue
        item = ev.get("item") or {}
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _populate_session(events: list[dict], result: RunResult) -> None:
    for ev in events:
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                result.subtype = thread_id
            return


def _populate_usage(events: list[dict], result: RunResult) -> None:
    for ev in events:
        if ev.get("type") != "turn.completed":
            continue
        usage = ev.get("usage") or {}
        if not isinstance(usage, dict):
            return
        in_tok = usage.get("input_tokens")
        if isinstance(in_tok, int):
            result.input_tokens = in_tok
        out_tok = usage.get("output_tokens")
        reason_tok = usage.get("reasoning_output_tokens")
        total_out = 0
        if isinstance(out_tok, int):
            total_out += out_tok
        if isinstance(reason_tok, int):
            total_out += reason_tok
        if total_out:
            result.output_tokens = total_out
        return
