from __future__ import annotations

import json
import logging

from agento.framework.agent_manager.errors import AuthenticationError
from agento.framework.runner import RunResult

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
        )

    # No result event (partial output from timeout) — return what we have
    if session_id:
        return RunResult(raw_output=raw, subtype=session_id)

    _log.warning(f"No result event in stream-json output: {raw[:500]}")
    return RunResult(raw_output=raw)


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
