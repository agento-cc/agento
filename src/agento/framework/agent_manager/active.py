"""Active-token resolution — purely DB-backed.

Prior versions mirrored the "active" token as a filesystem symlink under
``/etc/tokens/active/<agent_type>``. That indirection was removed when
credentials moved inline into ``oauth_token.credentials`` (encrypted): the
primary token for an agent_type is now the row with ``is_primary=TRUE``.
"""
from __future__ import annotations

import logging

import pymysql

from .models import AgentProvider, Token
from .token_store import get_primary_token, set_primary_token


def resolve_active_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
) -> Token | None:
    """Return the currently-active (primary) Token for ``agent_type``, or None."""
    return get_primary_token(conn, agent_type)


def update_active_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
    token: Token,
    logger: logging.Logger | None = None,
) -> None:
    """Mark ``token`` as the primary token for ``agent_type``."""
    set_primary_token(conn, agent_type, token.id, logger=logger)
    if logger:
        logger.info(
            f"Active token updated: agent_type={agent_type.value} "
            f"label={token.label} id={token.id}"
        )
