"""Module config resolution with 3-level fallback.

Mirrors the Node.js config-loader.js logic:
  1. ENV: CONFIG__{MODULE}__{FIELD}  (uppercase, hyphens -> underscores)
  2. DB:  core_config_data at path {module}/{field}
  3. config.json defaults in module directory

For tool fields the path includes "tools":
  ENV: CONFIG__{MODULE}__TOOLS__{TOOL}__{FIELD}
  DB:  {module}/tools/{tool}/{field}
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .encryptor import get_encryptor

logger = logging.getLogger(__name__)


@dataclass
class ResolvedValue:
    """A config value with its resolution source."""

    value: Any
    source: str  # "env", "db", "config.json", or "none"


def load_db_overrides(conn) -> dict[str, tuple[str, bool]]:
    """Batch-load all core_config_data rows into {path: (value, encrypted)}.

    Returns empty dict if conn is None or query fails.
    """
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT path, value, encrypted FROM core_config_data "
                "WHERE scope = 'default' AND scope_id = 0"
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
        logger.warning("Failed to load core_config_data overrides", exc_info=True)
        return {}


def read_config_defaults(module_path: Path) -> dict:
    """Read config.json from a module directory. Returns empty dict if absent."""
    config_path = module_path / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", config_path, exc)
        return {}


def _coerce_type(value: str, field_type: str) -> Any:
    """Coerce a string value to the declared field type."""
    if field_type == "integer":
        return int(value)
    if field_type == "boolean":
        return value.lower() in ("1", "true", "yes")
    if field_type == "json":
        return json.loads(value)
    # string, obscure -> return as-is
    return value


def _env_key(module_name: str, field_name: str) -> str:
    """Build ENV var name: CONFIG__{MODULE}__{FIELD} uppercase, hyphens -> underscores."""
    return f"CONFIG__{module_name}__{field_name}".upper().replace("-", "_")


def _env_key_tool(module_name: str, tool_name: str, field_name: str) -> str:
    """Build ENV var name for tool field."""
    return f"CONFIG__{module_name}__TOOLS__{tool_name}__{field_name}".upper().replace("-", "_")


def _db_path(module_name: str, field_name: str) -> str:
    """Build DB path: {module}/{field}, hyphens -> underscores."""
    return f"{module_name}/{field_name}".replace("-", "_")


def _db_path_tool(module_name: str, tool_name: str, field_name: str) -> str:
    """Build DB path for tool field."""
    return f"{module_name}/tools/{tool_name}/{field_name}".replace("-", "_")


def _resolve_from_db(
    db_path: str,
    db_overrides: dict[str, tuple[str, bool]],
) -> tuple[str | None, bool]:
    """Look up a DB override. Returns (value_or_None, found)."""
    override = db_overrides.get(db_path)
    if override is None:
        return None, False
    value, encrypted = override
    if encrypted:
        try:
            return get_encryptor().decrypt(value), True
        except Exception:
            logger.error("Failed to decrypt %s", db_path, exc_info=True)
            return None, False
    return value, True


def resolve_field(
    module_name: str,
    field_name: str,
    field_schema: dict,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> ResolvedValue:
    """Resolve a single module config field using 3-level fallback."""
    field_type = field_schema.get("type", "string")

    # 1. ENV var (highest priority)
    env_val = os.environ.get(_env_key(module_name, field_name))
    if env_val is not None:
        return ResolvedValue(value=_coerce_type(env_val, field_type), source="env")

    # 2. DB override
    db_val, found = _resolve_from_db(
        _db_path(module_name, field_name), db_overrides
    )
    if found and db_val is not None:
        return ResolvedValue(value=_coerce_type(db_val, field_type), source="db")

    # 3. config.json default
    cfg_val = config_defaults.get(field_name)
    if cfg_val is not None:
        return ResolvedValue(value=cfg_val, source="config.json")

    return ResolvedValue(value=None, source="none")


def resolve_tool_field(
    module_name: str,
    tool_name: str,
    field_name: str,
    field_schema: dict,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> ResolvedValue:
    """Resolve a single tool config field using 3-level fallback.

    Matches Node.js config-loader.js resolveField() exactly.
    """
    field_type = field_schema.get("type", "string")

    # 1. ENV var
    env_val = os.environ.get(_env_key_tool(module_name, tool_name, field_name))
    if env_val is not None:
        return ResolvedValue(value=_coerce_type(env_val, field_type), source="env")

    # 2. DB override
    db_val, found = _resolve_from_db(
        _db_path_tool(module_name, tool_name, field_name), db_overrides
    )
    if found and db_val is not None:
        return ResolvedValue(value=_coerce_type(db_val, field_type), source="db")

    # 3. config.json default (nested under tools/tool_name/field_name)
    cfg_val = config_defaults.get("tools", {}).get(tool_name, {}).get(field_name)
    if cfg_val is not None:
        return ResolvedValue(value=cfg_val, source="config.json")

    return ResolvedValue(value=None, source="none")


def resolve_module_config(
    manifest,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> dict[str, Any]:
    """Resolve all config fields declared in a module manifest.

    Returns {field_name: resolved_value}.
    """
    result = {}
    for field_name, field_schema in manifest.config.items():
        resolved = resolve_field(
            manifest.name, field_name, field_schema, config_defaults, db_overrides
        )
        result[field_name] = resolved.value
    return result


def resolve_module_config_with_sources(
    manifest,
    config_defaults: dict,
    db_overrides: dict[str, tuple[str, bool]],
) -> dict[str, ResolvedValue]:
    """Resolve all config fields with source information (for config:list display)."""
    result = {}
    for field_name, field_schema in manifest.config.items():
        result[field_name] = resolve_field(
            manifest.name, field_name, field_schema, config_defaults, db_overrides
        )
    return result
