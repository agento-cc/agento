from __future__ import annotations

import pymysql

from .config import AgentManagerConfig
from .models import AgentProvider, Token
from .rotator import select_best_token
from .token_store import list_tokens
from .usage_store import get_usage_summaries


class TokenResolver:
    """Resolve which oauth_token to use for a given provider.

    Single responsibility: given an AgentProvider, return the Token
    to execute with.  Encapsulates selection logic — future extension
    point for pools, capacity routing, etc.
    """

    def __init__(self, config: AgentManagerConfig | None = None) -> None:
        self._config = config or AgentManagerConfig()

    def resolve(self, conn: pymysql.Connection, agent_type: AgentProvider) -> Token:
        """Return the best token for the given provider.

        Strategy:
        1. List enabled tokens for the provider.
        2. Use select_best_token() rotation logic
           (is_primary sticky, then capacity-based fallback).
        3. Raise if no tokens available.
        """
        tokens = list_tokens(conn, agent_type=agent_type, enabled_only=True)
        if not tokens:
            raise RuntimeError(
                f"No enabled tokens for provider={agent_type.value}. "
                f"Register tokens first: bin/agento token:register "
                f"{agent_type.value} <label> <path>"
            )
        summaries = get_usage_summaries(
            conn, agent_type.value, self._config.usage_window_hours,
        )
        usage_map = {s.token_id: s for s in summaries}
        best = select_best_token(tokens, usage_map)
        # select_best_token returns None only when tokens is empty, already guarded
        return best  # type: ignore[return-value]
