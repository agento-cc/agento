from __future__ import annotations

import json
import logging

from agento.framework.runner import RunResult

AUTH_ERROR_PHRASES = (
    "authentication_error",
    "OAuth token has expired",
    "Not logged in",
    "401",
)


class AuthenticationError(RuntimeError):
    """Raised when Claude CLI fails due to expired or missing OAuth credentials."""


# Backward-compatible alias — all existing imports of ClaudeResult keep working.
ClaudeResult = RunResult


def parse_claude_output(raw: str, logger: logging.Logger | None = None) -> RunResult:
    """Parse Claude CLI JSON output into a RunResult."""
    _log = logger or logging.getLogger(__name__)
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
