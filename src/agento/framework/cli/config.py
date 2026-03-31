from __future__ import annotations

import argparse
import json

from ..db import get_connection_or_exit
from .runtime import _load_framework_config


def cmd_config_set(args: argparse.Namespace) -> None:
    from ..core_config import config_set_auto_encrypt
    from ..event_manager import get_event_manager
    from ..events import ConfigSavedEvent

    scope = getattr(args, "scope", "default")
    scope_id = getattr(args, "scope_id", 0)
    scope_label = f" [scope={scope}, scope_id={scope_id}]" if scope != "default" else ""

    db_config, _, _ = _load_framework_config()
    conn = get_connection_or_exit(db_config)
    try:
        encrypted = config_set_auto_encrypt(
            conn, args.path, args.value, scope=scope, scope_id=scope_id
        )
        conn.commit()
        get_event_manager().dispatch(
            "agento_config_saved",
            ConfigSavedEvent(path=args.path, encrypted=encrypted),
        )
        label = " (encrypted)" if encrypted else ""
        print(f"Set: {args.path}{label}{scope_label}")
    finally:
        conn.close()


def cmd_config_remove(args: argparse.Namespace) -> None:
    from ..core_config import config_delete

    scope = getattr(args, "scope", "default")
    scope_id = getattr(args, "scope_id", 0)
    scope_label = f" [scope={scope}, scope_id={scope_id}]" if scope != "default" else ""

    db_config, _, _ = _load_framework_config()
    conn = get_connection_or_exit(db_config)
    try:
        deleted = config_delete(conn, args.path, scope=scope, scope_id=scope_id)
        conn.commit()
        if deleted:
            print(f"Removed: {args.path}{scope_label}")
        else:
            print(f"Not found: {args.path}{scope_label}")
    finally:
        conn.close()


def cmd_config_get(args: argparse.Namespace) -> None:
    path = args.path
    # Exact path: has / (e.g. core/allowed_domains, jira/tools/mysql_.../host)
    # Prefix/tree: no / (e.g. jira, core)
    is_exact = "/" in path

    db_config, _, _ = _load_framework_config()
    conn = get_connection_or_exit(db_config)
    try:
        if is_exact:
            _config_get_exact(conn, path)
        else:
            _config_get_tree(conn, path)
    finally:
        conn.close()


def _config_get_exact(conn, path: str) -> None:
    """Display config value for exact path, deduplicated across scopes."""
    from ..core_config import config_get

    rows = config_get(conn, path)
    if not rows:
        print(f"Not set: {path}")
        return

    # Mask obscure values (encrypted or declared obscure in schema)
    for row in rows:
        row["display"] = "****" if row.get("obscure") else row["value"]

    # Deduplicate: if all display values are the same, show one line
    values = {r["display"] for r in rows}
    if len(values) == 1:
        print(f"  {path} = {rows[0]['display']}")
        return

    for row in rows:
        scope_tag = _format_scope_tag(conn, row["scope"], row["scope_id"])
        print(f"  {path} = {row['display']}  [{scope_tag}]")


def _config_get_tree(conn, prefix: str) -> None:
    """Display all config for a module prefix in tree view grouped by scope."""
    from collections import OrderedDict

    from ..bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR
    from ..config_resolver import read_config_defaults
    from ..core_config import config_get_tree
    from ..module_loader import scan_modules

    rows = config_get_tree(conn, prefix + "/")

    # Also load config.json defaults for the module
    manifests = scan_modules(CORE_MODULES_DIR) + scan_modules(USER_MODULES_DIR)
    manifest = next((m for m in manifests if m.name == prefix.replace("-", "_")), None)
    config_defaults = read_config_defaults(manifest.path) if manifest else {}

    # Build config.json entries (tool fields)
    cfg_entries = {}
    if config_defaults.get("tools"):
        for tool_name, fields in config_defaults["tools"].items():
            for field_name, value in fields.items():
                cfg_path = f"{prefix}/tools/{tool_name}/{field_name}"
                cfg_entries[cfg_path] = value

    # Group DB rows by (scope, scope_id)
    groups: OrderedDict[tuple[str, int, str], list[dict]] = OrderedDict()

    # Ensure default group exists first
    groups[("default", 0, "")] = []

    for row in rows:
        key = (row["scope"], row["scope_id"], row["scope_label"])
        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    # Add config.json defaults to default group (if not overridden by DB)
    db_paths_default = {r["path"] for r in groups.get(("default", 0, ""), [])}
    for cfg_path, cfg_value in cfg_entries.items():
        if cfg_path not in db_paths_default:
            groups[("default", 0, "")].append({
                "path": cfg_path, "value": str(cfg_value), "source": "config.json",
            })

    if all(len(entries) == 0 for entries in groups.values()):
        print(f"No config found for: {prefix}")
        return

    print(f"  {prefix}")
    group_list = list(groups.items())
    for i, ((scope, scope_id, scope_label), entries) in enumerate(group_list):
        if not entries:
            continue
        is_last = all(len(e) == 0 for _, e in group_list[i + 1:])

        # Scope header
        if scope == "default":
            header = "default"
        elif scope_label:
            header = f"{scope}: {scope_label} (id={scope_id})"
        else:
            header = f"{scope}/{scope_id}"

        connector = "\u2514" if is_last else "\u251c"
        pipe = " " if is_last else "\u2502"
        print(f"  {connector} {header}")

        for entry in sorted(entries, key=lambda e: e["path"]):
            # Strip module prefix from path for cleaner display
            display_path = entry["path"]
            if display_path.startswith(prefix + "/"):
                display_path = display_path[len(prefix) + 1:]
            source = f"  [{entry.get('source', '')}]" if entry.get("source") else ""
            print(f"  {pipe}   {display_path} = {entry['value']}{source}")


def _format_scope_tag(conn, scope: str, scope_id: int) -> str:
    """Format a human-readable scope tag like 'default' or 'agent_view: Jira'."""
    if scope == "default":
        return "default"
    if scope == "workspace":
        from ..workspace import get_workspace
        ws = get_workspace(conn, scope_id)
        return f"workspace: {ws.code}" if ws else f"workspace/{scope_id}"
    if scope == "agent_view":
        from ..workspace import get_agent_view
        av = get_agent_view(conn, scope_id)
        return f"agent_view: {av.code}" if av else f"agent_view/{scope_id}"
    return f"{scope}/{scope_id}"


def cmd_config_list(args: argparse.Namespace) -> None:
    from ..bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR
    from ..config_resolver import (
        load_db_overrides,
        read_config_defaults,
        resolve_module_config_with_sources,
        resolve_tool_field,
    )
    from ..core_config import config_list
    from ..module_loader import scan_modules

    db_config, _, _ = _load_framework_config()
    conn = get_connection_or_exit(db_config)
    try:
        prefix = args.prefix or ""

        # Show resolved module config (3-level fallback with sources)
        manifests = scan_modules(CORE_MODULES_DIR) + scan_modules(USER_MODULES_DIR)
        db_overrides = load_db_overrides(conn)
        shown_module_config = False

        for m in manifests:
            if prefix and not m.name.startswith(prefix):
                continue
            if m.config:
                config_defaults = read_config_defaults(m.path)
                resolved = resolve_module_config_with_sources(
                    m, config_defaults, db_overrides
                )
                for field_name, rv in resolved.items():
                    display = "****" if rv.source == "db" and _is_field_obscure(m, field_name) else _format_value(rv.value)
                    print(f"  {m.name}/{field_name} = {display}  [{rv.source}]")
                    shown_module_config = True

            # Show resolved tool config
            for tool in m.tools:
                if prefix and not f"{m.name}/tools/{tool['name']}".startswith(prefix):
                    continue
                config_defaults = read_config_defaults(m.path)
                for field_name, field_schema in tool.get("fields", {}).items():
                    rv = resolve_tool_field(
                        m.name, tool["name"], field_name,
                        field_schema, config_defaults, db_overrides,
                    )
                    is_obscure = field_schema.get("type") == "obscure"
                    display = "****" if is_obscure and rv.value else _format_value(rv.value)
                    print(f"  {m.name}/tools/{tool['name']}/{field_name} = {display}  [{rv.source}]")
                    shown_module_config = True

        # Also show raw DB overrides not covered by module manifests
        if not shown_module_config:
            entries = config_list(conn, prefix=prefix)
            if not entries:
                print("No config entries found.")
                return
            for entry in entries:
                enc = " [encrypted]" if entry["encrypted"] else ""
                scope_label = f"{entry['scope']}/{entry['scope_id']}"
                print(f"  {entry['path']} = {entry['value']}{enc}  [{scope_label}]")
    finally:
        conn.close()


def _is_field_obscure(manifest, field_name: str) -> bool:
    """Check if a module config field is obscure type."""
    schema = manifest.config.get(field_name, {})
    return schema.get("type") == "obscure"


def _format_value(value: object) -> str:
    """Format a config value for display."""
    if value is None:
        return "(not set)"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
