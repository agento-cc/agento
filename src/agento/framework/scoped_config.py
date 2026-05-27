"""Scope constants + DB-override loading for scoped config resolution.

The ENV -> DB -> config.json fallback itself lives in a single place —
``ScopedConfigService`` in ``config_resolver.py``. This module only provides:

  * ``Scope`` constants (default / workspace / agent_view),
  * ``load_scoped_db_overrides`` / ``build_scoped_overrides`` — load and merge
    ``core_config_data`` rows across the 3-tier scope chain (agent_view ->
    workspace -> default), the DB tier the service resolves against,
  * ``scoped_config_set`` — write a scoped value.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Scope:
    """Magento-style scope constants for 3-tier config resolution."""

    DEFAULT = "default"
    WORKSPACE = "workspace"
    AGENT_VIEW = "agent_view"


def load_scoped_db_overrides(
    conn,
    scope: str = Scope.DEFAULT,
    scope_id: int = 0,
) -> dict[str, tuple[str, bool]]:
    """Load core_config_data rows for a specific (scope, scope_id).

    Returns {path: (value, encrypted)}.
    """
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT path, value, encrypted FROM core_config_data "
                "WHERE scope = %s AND scope_id = %s",
                (scope, scope_id),
            )
            rows = cur.fetchall()
        result = {}
        for row in rows:
            if isinstance(row, dict):
                result[row["path"]] = (row["value"], bool(row["encrypted"]))
            else:
                result[row[0]] = (row[1], bool(row[2]))
        return result
    except Exception:
        logger.warning("Failed to load scoped overrides (%s/%s)", scope, scope_id, exc_info=True)
        return {}


def build_scoped_overrides(
    conn,
    agent_view_id: int | None = None,
    workspace_id: int | None = None,
) -> dict[str, tuple[str, bool]]:
    """Build merged DB overrides with 3-tier fallback: agent_view -> workspace -> global.

    Later tiers (more specific) override earlier ones for the same path.
    """
    # Start with global
    merged = load_scoped_db_overrides(conn, Scope.DEFAULT, 0)

    # Layer workspace overrides
    if workspace_id is not None:
        ws_overrides = load_scoped_db_overrides(conn, Scope.WORKSPACE, workspace_id)
        merged.update(ws_overrides)

    # Layer agent_view overrides (most specific)
    if agent_view_id is not None:
        av_overrides = load_scoped_db_overrides(conn, Scope.AGENT_VIEW, agent_view_id)
        merged.update(av_overrides)

    return merged


def scoped_config_set(
    conn,
    path: str,
    value: str,
    *,
    scope: str = Scope.DEFAULT,
    scope_id: int = 0,
    encrypted: bool = False,
) -> None:
    """Set a scoped config value (INSERT or UPDATE)."""
    from .encryptor import get_encryptor

    stored_value = get_encryptor().encrypt(value) if encrypted else value
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO core_config_data (scope, scope_id, path, value, encrypted)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE value = VALUES(value), encrypted = VALUES(encrypted)""",
            (scope, scope_id, path, stored_value, int(encrypted)),
        )
