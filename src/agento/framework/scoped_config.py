"""Scoped config resolution with 3-tier DB fallback: agent_view -> workspace -> global.

Extends the existing 3-level fallback (ENV -> DB -> config.json) by making
the DB lookup scope-aware. For a given (scope, scope_id), resolution checks:
  1. agent_view scope (scope_id = agent_view.id)
  2. workspace scope (scope_id = workspace.id)
  3. default scope (scope_id = 0, i.e. global)

ENV always wins. config.json is the final fallback.
"""
from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

from .config_resolver import ResolvedValue, _coerce_type, _env_key, _env_key_tool, _resolve_from_db

logger = logging.getLogger(__name__)


def load_scoped_db_overrides(
    conn,
    scope: str = "default",
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
    merged = load_scoped_db_overrides(conn, "default", 0)

    # Layer workspace overrides
    if workspace_id is not None:
        ws_overrides = load_scoped_db_overrides(conn, "workspace", workspace_id)
        merged.update(ws_overrides)

    # Layer agent_view overrides (most specific)
    if agent_view_id is not None:
        av_overrides = load_scoped_db_overrides(conn, "agent_view", agent_view_id)
        merged.update(av_overrides)

    return merged


def resolve_scoped_field(
    module_name: str,
    field_name: str,
    field_schema: dict,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> ResolvedValue:
    """Resolve a single config field using scoped 3-level fallback.

    db_overrides should already be merged via build_scoped_overrides().
    """
    field_type = field_schema.get("type", "string")

    # 1. ENV (highest priority, always global)
    env_val = os.environ.get(_env_key(module_name, field_name))
    if env_val is not None:
        return ResolvedValue(value=_coerce_type(env_val, field_type), source="env")

    # 2. Scoped DB override (already merged: agent_view > workspace > global)
    db_path = f"{module_name}/{field_name}".replace("-", "_")
    db_val, found = _resolve_from_db(db_path, db_overrides)
    if found and db_val is not None:
        return ResolvedValue(value=_coerce_type(db_val, field_type), source="db")

    # 3. config.json default
    cfg_val = config_defaults.get(field_name)
    if cfg_val is not None:
        return ResolvedValue(value=cfg_val, source="config.json")

    return ResolvedValue(value=None, source="none")


def resolve_scoped_tool_field(
    module_name: str,
    tool_name: str,
    field_name: str,
    field_schema: dict,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> ResolvedValue:
    """Resolve a single tool config field with scoped DB fallback."""
    field_type = field_schema.get("type", "string")

    # 1. ENV
    env_val = os.environ.get(_env_key_tool(module_name, tool_name, field_name))
    if env_val is not None:
        return ResolvedValue(value=_coerce_type(env_val, field_type), source="env")

    # 2. Scoped DB
    db_path = f"{module_name}/tools/{tool_name}/{field_name}".replace("-", "_")
    db_val, found = _resolve_from_db(db_path, db_overrides)
    if found and db_val is not None:
        return ResolvedValue(value=_coerce_type(db_val, field_type), source="db")

    # 3. config.json
    cfg_val = config_defaults.get("tools", {}).get(tool_name, {}).get(field_name)
    if cfg_val is not None:
        return ResolvedValue(value=cfg_val, source="config.json")

    return ResolvedValue(value=None, source="none")


def resolve_scoped_module_config(
    manifest,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> dict[str, Any]:
    """Resolve all config fields for a module using scoped DB overrides."""
    result = {}
    for field_name, field_schema in manifest.config.items():
        resolved = resolve_scoped_field(
            manifest.name, field_name, field_schema, config_defaults, db_overrides
        )
        result[field_name] = resolved.value
    return result


def scoped_config_set(
    conn,
    path: str,
    value: str,
    *,
    scope: str = "default",
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


class ScopedConfig:
    """Magento-like config service with recursive scope fallback."""

    _SCOPE_CHAIN: ClassVar[dict[str, str]] = {
        "agent_view": "workspace",
        "workspace": "default",
    }

    def __init__(self, conn, scope: str = "default", scope_id: int = 0):
        self._conn = conn
        self._scope = scope
        self._scope_id = scope_id
        self._workspace_id: int | None = None
        self._workspace_id_resolved = False

    def get_value(self, path: str) -> str | None:
        """Recursive fallback: ENV -> DB(agent_view) -> DB(workspace) -> DB(default) -> config.json"""
        # 1. ENV override
        env_val = os.environ.get(self._path_to_env_key(path))
        if env_val is not None:
            return env_val

        # 2. Recursive DB fallback
        db_val = self._resolve_db(self._scope, self._scope_id, path)
        if db_val is not None:
            return db_val

        # 3. config.json fallback
        return self._resolve_config_json(path)

    def _resolve_db(self, scope: str, scope_id: int, path: str) -> str | None:
        """Try DB at given scope, then walk up the scope chain."""
        val = self._query_db(scope, scope_id, path)
        if val is not None:
            return val

        parent_scope = self._SCOPE_CHAIN.get(scope)
        if parent_scope is None:
            return None

        if scope == "agent_view":
            parent_id = self._resolve_workspace_id()
            if parent_id is None:
                # Skip workspace, try default
                return self._resolve_db("default", 0, path)
            return self._resolve_db("workspace", parent_id, path)

        # workspace -> default
        return self._resolve_db("default", 0, path)

    def _query_db(self, scope: str, scope_id: int, path: str) -> str | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT value, encrypted FROM core_config_data "
                "WHERE scope=%s AND scope_id=%s AND path=%s",
                (scope, scope_id, path),
            )
            row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            value, encrypted = row["value"], bool(row["encrypted"])
        else:
            value, encrypted = row[0], bool(row[1])
        if encrypted:
            from .encryptor import get_encryptor
            return get_encryptor().decrypt(value)
        return value

    def _resolve_workspace_id(self) -> int | None:
        if self._workspace_id_resolved:
            return self._workspace_id
        self._workspace_id_resolved = True
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id FROM agent_view WHERE id=%s",
                (self._scope_id,),
            )
            row = cur.fetchone()
            if row:
                if isinstance(row, dict):
                    self._workspace_id = row["workspace_id"]
                else:
                    self._workspace_id = row[0]
        return self._workspace_id

    def _resolve_config_json(self, path: str) -> str | None:
        parts = path.split("/")
        module_name = parts[0]

        from .bootstrap import get_manifests
        from .config_resolver import read_config_defaults

        module_path = None
        for m in get_manifests():
            if m.name == module_name:
                module_path = m.path
                break
        if module_path is None:
            return None

        defaults = read_config_defaults(module_path)
        if not defaults:
            return None

        if "tools" in parts and len(parts) >= 4:
            # module/tools/tool_name/field
            tool_name = parts[2]
            field_name = parts[3]
            val = defaults.get("tools", {}).get(tool_name, {}).get(field_name)
        elif len(parts) >= 2:
            field_name = parts[1]
            val = defaults.get(field_name)
        else:
            return None

        return str(val) if val is not None else None

    @staticmethod
    def _path_to_env_key(path: str) -> str:
        parts = path.split("/")
        module_name = parts[0]

        if "tools" in parts and len(parts) >= 4:
            tool_name = parts[2]
            field_name = parts[3]
            return _env_key_tool(module_name, tool_name, field_name)

        if len(parts) >= 2:
            field_name = parts[1]
            return _env_key(module_name, field_name)

        return f"CONFIG__{module_name}".upper().replace("-", "_")
