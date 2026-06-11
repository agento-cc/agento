from __future__ import annotations

import json
import logging

from agento.framework.agent_manager.errors import AuthenticationError
from agento.framework.runner import McpInitReport, McpServerStatus, RunResult

AUTH_ERROR_PHRASES = (
    "authentication_error",
    "OAuth token has expired",
    "Not logged in",
    "401",
)


# Backward-compatible alias — all existing imports of ClaudeResult keep working.
ClaudeResult = RunResult

__all__ = ["AUTH_ERROR_PHRASES", "AuthenticationError", "ClaudeResult", "parse_claude_output"]


def parse_claude_output(raw: str, logger: logging.Logger | None = None) -> RunResult:
    """Parse Claude CLI stream-json (JSONL) output into a RunResult.

    Falls back to single-JSON parsing for backward compatibility.
    """
    _log = logger or logging.getLogger(__name__)

    # Backward compat: single JSON object (old --output-format json)
    stripped = raw.strip()
    if stripped.startswith("{") and "\n" not in stripped:
        try:
            data = json.loads(stripped)
            # Old format has "result", "is_error", or "usage" at top level
            # Stream-json events have "type" as their discriminator
            if isinstance(data, dict) and "type" not in data:
                return _parse_single_json(raw, _log)
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse JSONL events line by line
    session_id: str | None = None
    result_event: dict | None = None
    mcp_init: McpInitReport | None = None
    init_seen = False

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(event, dict):
            continue

        if event.get("session_id"):
            session_id = event["session_id"]

        # First `system/init` event wins; ignore any subsequent ones.
        if (
            not init_seen
            and event.get("type") == "system"
            and event.get("subtype") == "init"
            and isinstance(event.get("mcp_servers"), list)
        ):
            init_seen = True
            mcp_init = _extract_mcp_init(event["mcp_servers"])
            if mcp_init is not None:
                # Log only sanitized name/status pairs — never the raw event,
                # which can carry prompts, tool arguments, and customer data.
                _log.debug(
                    "mcp init: %s",
                    [(s.name, s.status) for s in mcp_init.servers],
                )

        if event.get("type") == "result":
            result_event = event

    if result_event:
        if result_event.get("is_error"):
            msg = result_event.get("result", "unknown error")
            if any(p in msg for p in AUTH_ERROR_PHRASES):
                raise AuthenticationError(f"Claude CLI error: {msg}")
            raise RuntimeError(f"Claude CLI error: {msg}")

        usage = result_event.get("usage", {})
        return RunResult(
            raw_output=raw,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cost_usd=result_event.get("total_cost_usd"),
            num_turns=result_event.get("num_turns"),
            duration_ms=result_event.get("duration_ms"),
            subtype=session_id or result_event.get("session_id"),
            mcp_init=mcp_init,
        )

    # No result event (partial output from timeout) — return what we have
    if session_id:
        return RunResult(raw_output=raw, subtype=session_id, mcp_init=mcp_init)

    _log.warning(f"No result event in stream-json output: {raw[:500]}")
    return RunResult(raw_output=raw, mcp_init=mcp_init)


def _extract_mcp_init(servers: list) -> McpInitReport | None:
    """Build an McpInitReport from a claude ``system/init`` event's mcp_servers.

    An empty list yields ``McpInitReport(servers=())`` — a valid "no MCP servers
    visible" report, distinct from ``None`` ("no init report at all"). A malformed
    entry (not a dict, or missing string name/status) makes the whole report
    untrustworthy → return ``None`` and never raise.
    """
    parsed: list[McpServerStatus] = []
    for entry in servers:
        if not isinstance(entry, dict):
            return None
        name = entry.get("name")
        status = entry.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            return None
        parsed.append(McpServerStatus(name=name, status=status))
    return McpInitReport(servers=tuple(parsed))


def _parse_single_json(raw: str, _log: logging.Logger) -> RunResult:
    """Parse Claude CLI single JSON output into a RunResult (legacy format)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        _log.warning(f"Claude output is not valid JSON ({exc}): {raw[:500]}")
        return RunResult(raw_output=raw)

    if data.get("is_error"):
        msg = data.get("result", "unknown error")
        if any(p in msg for p in AUTH_ERROR_PHRASES):
            raise AuthenticationError(f"Claude CLI error: {msg}")
        raise RuntimeError(f"Claude CLI error: {msg}")

    cr = RunResult(
        raw_output=raw,
        input_tokens=data.get("usage", {}).get("input_tokens"),
        output_tokens=data.get("usage", {}).get("output_tokens"),
        cost_usd=data.get("total_cost_usd"),
        num_turns=data.get("num_turns"),
        duration_ms=data.get("duration_ms"),
        subtype=data.get("subtype"),
    )
    if cr.num_turns is None and cr.input_tokens is None:
        _log.warning(f"Claude JSON has no usage data, keys={list(data.keys())}")
    return cr
