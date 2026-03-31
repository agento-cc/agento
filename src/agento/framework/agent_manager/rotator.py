from __future__ import annotations

import logging
from datetime import datetime, timezone

import pymysql

from .active import resolve_active_token, update_active_token
from .config import AgentManagerConfig
from .models import AgentProvider, RotationResult, Token, UsageSummary
from .token_store import get_token_by_path, list_tokens
from .usage_store import get_usage_summaries


def select_best_token(
    tokens: list[Token],
    usage_map: dict[int, UsageSummary],
) -> Token | None:
    """Pick the token with the most remaining capacity.

    Algorithm:
    0. If any token has is_primary=True, return it immediately (sticky selection).
    1. For each token, compute remaining = token_limit - total_tokens_used.
       If token_limit == 0 (unlimited), remaining is infinity.
    2. Return the token with the highest remaining capacity.
    3. Tie-break: prefer the token with fewer total calls.
    4. Returns None if no tokens available.
    """
    if not tokens:
        return None

    # Respect manually-set primary token
    for t in tokens:
        if t.is_primary:
            return t

    def _sort_key(t: Token) -> tuple[float, int]:
        summary = usage_map.get(t.id)
        used = summary.total_tokens if summary else 0
        calls = summary.call_count if summary else 0
        remaining = float("inf") if t.token_limit == 0 else (t.token_limit - used)
        # Negate remaining so highest is first; use calls as tie-break (fewer = better)
        return (-remaining, calls)

    return min(tokens, key=_sort_key)


def rotate_tokens(
    conn: pymysql.Connection,
    config: AgentManagerConfig,
    agent_type: AgentProvider,
    logger: logging.Logger | None = None,
) -> RotationResult | None:
    """Perform rotation for a single agent type."""
    _log = logger or logging.getLogger(__name__)

    tokens = list_tokens(conn, agent_type=agent_type, enabled_only=True)
    if not tokens:
        _log.warning(f"No enabled tokens for agent_type={agent_type.value}")
        return None

    # Current active
    active_path = resolve_active_token(config, agent_type)
    previous_token = get_token_by_path(conn, active_path) if active_path else None

    # Usage summaries
    summaries = get_usage_summaries(conn, agent_type.value, config.usage_window_hours)
    usage_map = {s.token_id: s for s in summaries}

    best = select_best_token(tokens, usage_map)
    if best is None:
        return None

    # Update symlink if changed (or if no active token yet)
    if previous_token is None or previous_token.id != best.id:
        update_active_token(config, agent_type, best, logger)
        reason = "initial" if previous_token is None else "rotation"
    else:
        reason = "unchanged"

    return RotationResult(
        agent_type=agent_type,
        previous_token_id=previous_token.id if previous_token else None,
        new_token_id=best.id,
        reason=reason,
        timestamp=datetime.now(timezone.utc),
    )


def rotate_all(
    conn: pymysql.Connection,
    config: AgentManagerConfig,
    logger: logging.Logger | None = None,
) -> list[RotationResult]:
    """Rotate tokens for all known agent types."""
    results = []
    for agent_type in AgentProvider:
        result = rotate_tokens(conn, config, agent_type, logger)
        if result:
            results.append(result)
    return results
