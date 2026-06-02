from __future__ import annotations

import time

import pymysql

from .config import AgentManagerConfig
from .models import AgentProvider, Token
from .token_store import count_tokens_for_provider, select_token

_POOL_CONTENTION_RETRIES = 20
_POOL_CONTENTION_SLEEP_SECONDS = 0.01


class TokenResolver:
    """Resolve which oauth_token to use for a given provider.

    Selection is LRU over the pool of healthy tokens (``status='ok'`` and
    unexpired). Sticky-primary semantics are gone — running jobs fan out over
    every enabled license so capacity is shared fairly.
    """

    def __init__(self, config: AgentManagerConfig | None = None) -> None:
        self._config = config or AgentManagerConfig()

    def resolve(self, conn: pymysql.Connection, agent_type: AgentProvider) -> Token:
        """Return the least-recently-used healthy token for ``agent_type``.

        Raises ``RuntimeError`` with an actionable message when no healthy
        token is available (distinguishes "none registered" vs
        "all errored/expired" so the operator knows whether to ``token:register``,
        ``token:refresh``, or ``token:reset``).
        """
        total = 0
        healthy = 0
        for attempt in range(_POOL_CONTENTION_RETRIES + 1):
            token = select_token(conn, agent_type)
            if token is not None:
                return token

            total, healthy = count_tokens_for_provider(conn, agent_type)
            if total == 0 or healthy == 0:
                break
            if attempt < _POOL_CONTENTION_RETRIES:
                time.sleep(_POOL_CONTENTION_SLEEP_SECONDS)

        if total == 0:
            raise RuntimeError(
                f"No enabled tokens for provider={agent_type.value}. "
                f"Register one: bin/agento token:register {agent_type.value} <label>"
            )
        if healthy > 0:
            raise RuntimeError(
                f"All {healthy} healthy tokens for provider={agent_type.value} are "
                "currently locked by concurrent workers; retry shortly."
            )
        raise RuntimeError(
            f"All {total} enabled tokens for provider={agent_type.value} are "
            f"unhealthy (errored or expired); {healthy} healthy. "
            f"Run 'bin/agento token:list --all' to inspect, then "
            f"'bin/agento token:refresh <id>' or 'bin/agento token:reset <id>'."
        )
