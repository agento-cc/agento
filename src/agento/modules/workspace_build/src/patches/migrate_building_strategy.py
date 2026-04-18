"""Data patch: migrate legacy ``workspace_build/building_strategy`` to per-source keys.

Before this release, a single global setting controlled only module workspace
layering. The new model introduces three per-source strategy keys:

    workspace_build/strategy/theme
    workspace_build/strategy/modules
    workspace_build/strategy/skills

The old key's semantic scope was module workspaces, so its value migrates to
``workspace_build/strategy/modules``. Theme and skills retain the "copy"
default.

Behaviour:
- For every ``core_config_data`` row with path ``workspace_build/building_strategy``
  (any scope / scope_id), insert or update a corresponding
  ``workspace_build/strategy/modules`` row with the same value and scope, then
  delete the old row.
- If the destination row already exists with a different value, the existing
  destination wins (operator may have already set the new key explicitly); the
  old row is still removed to keep state clean.
- Idempotent — running again when no old rows exist is a no-op.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_OLD_PATH = "workspace_build/building_strategy"
_NEW_PATH = "workspace_build/strategy/modules"


class MigrateBuildingStrategy:
    """Rename ``workspace_build/building_strategy`` → ``workspace_build/strategy/modules``."""

    def apply(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT scope, scope_id, value, encrypted FROM core_config_data "
                "WHERE path = %s",
                (_OLD_PATH,),
            )
            rows = cur.fetchall()

        if not rows:
            return

        for row in rows:
            scope = row["scope"]
            scope_id = row["scope_id"]
            value = row["value"]
            encrypted = int(bool(row["encrypted"]))

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM core_config_data "
                    "WHERE scope = %s AND scope_id = %s AND path = %s",
                    (scope, scope_id, _NEW_PATH),
                )
                dest_exists = cur.fetchone() is not None

            if not dest_exists:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO core_config_data (scope, scope_id, path, value, encrypted) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (scope, scope_id, _NEW_PATH, value, encrypted),
                    )
                logger.info(
                    "Migrated %s=%r → %s (scope=%s scope_id=%s)",
                    _OLD_PATH, value, _NEW_PATH, scope, scope_id,
                )
            else:
                logger.info(
                    "Destination %s already exists at scope=%s scope_id=%s — "
                    "keeping existing value and dropping old %s row",
                    _NEW_PATH, scope, scope_id, _OLD_PATH,
                )

            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM core_config_data "
                    "WHERE scope = %s AND scope_id = %s AND path = %s",
                    (scope, scope_id, _OLD_PATH),
                )

        conn.commit()

    def require(self) -> list[str]:
        return []
