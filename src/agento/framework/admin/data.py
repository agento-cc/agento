from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DashboardData:
    version: str = ""
    python_version: str = ""
    db_connected: bool = False
    module_count: int = 0
    running_jobs: int = 0
    recent_jobs: list[dict] = field(default_factory=list)
    tokens: list[dict] = field(default_factory=list)
    agent_views: list[dict] = field(default_factory=list)


@dataclass
class ModuleSchema:
    name: str
    fields: dict  # field_name -> {type, label, ...}
    tools: dict  # tool_name -> {field_name -> {type, label}}


@dataclass
class ResolvedField:
    path: str
    field_name: str
    value: str | None
    display_value: str
    source: str  # "env", "db", "db:inherited", "json", "none"
    field_type: str
    label: str
    obscure: bool


def _count_modules() -> int:
    from ..bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR

    count = 0
    for modules_dir in (CORE_MODULES_DIR, USER_MODULES_DIR):
        base = Path(modules_dir)
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.is_dir() and not entry.name.startswith("_") and (entry / "module.json").exists():
                count += 1
    return count


def get_dashboard_data(conn) -> DashboardData:
    from ..cli._templates import get_package_version

    data = DashboardData(
        version=get_package_version(),
        python_version=sys.version.split()[0],
    )

    # DB connection check
    if conn is not None:
        try:
            conn.ping(reconnect=True)
            data.db_connected = True
        except Exception:
            data.db_connected = False

    # Module count (filesystem-based, no DB needed)
    with contextlib.suppress(Exception):
        data.module_count = _count_modules()

    if not data.db_connected:
        return data

    # Running jobs
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM job WHERE status='RUNNING'")
            row = cur.fetchone()
            data.running_jobs = row["cnt"]
    except Exception:
        pass

    # Recent jobs
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT j.id, j.type, j.status, j.reference_id, j.created_at, j.finished_at, "
                "av.code AS agent_view_code "
                "FROM job j LEFT JOIN agent_view av ON j.agent_view_id = av.id "
                "ORDER BY j.id DESC LIMIT 3"
            )
            data.recent_jobs = cur.fetchall()
    except Exception:
        pass

    # Tokens
    try:
        from ..agent_manager.token_store import list_tokens

        tokens = list_tokens(conn, enabled_only=False)
        data.tokens = [
            {
                "id": t.id,
                "agent_type": t.agent_type.value,
                "label": t.label,
                "model": t.model,
                "is_primary": t.is_primary,
                "enabled": t.enabled,
            }
            for t in tokens
        ]
    except Exception:
        pass

    # Agent views
    try:
        from ..workspace import get_active_agent_views

        views = get_active_agent_views(conn)
        data.agent_views = [
            {"id": av.id, "code": av.code, "label": av.label, "workspace_id": av.workspace_id}
            for av in views
        ]
    except Exception:
        pass

    return data


def get_jobs(conn, *, limit: int = 50, offset: int = 0, status: str | None = None, search: str | None = None) -> list[dict]:
    if conn is None:
        return []
    try:
        sql = (
            "SELECT j.id, j.type, j.status, j.reference_id, j.agent_type, "
            "j.created_at, j.started_at, j.finished_at, j.input_tokens, j.output_tokens, "
            "av.code AS agent_view_code "
            "FROM job j LEFT JOIN agent_view av ON j.agent_view_id = av.id"
        )
        params: list = []
        conditions = []
        if status:
            conditions.append("j.status = %s")
            params.append(status)
        if search:
            conditions.append("j.reference_id LIKE %s")
            params.append(f"%{search}%")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY j.id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:
        return []


def get_job_detail(conn, job_id: int) -> dict | None:
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT j.*, av.code AS agent_view_code "
                "FROM job j LEFT JOIN agent_view av ON j.agent_view_id = av.id "
                "WHERE j.id = %s",
                (job_id,),
            )
            return cur.fetchone()
    except Exception:
        return None


def get_tokens_with_usage(conn, *, window_hours: int = 24) -> list[dict]:
    if conn is None:
        return []
    try:
        from ..agent_manager.token_store import list_tokens
        from ..agent_manager.usage_store import get_usage_summary

        tokens = list_tokens(conn, enabled_only=False)
        results = []
        for t in tokens:
            usage = get_usage_summary(conn, t.id, window_hours)
            pct_free = 100.0
            if t.token_limit > 0:
                pct_free = max(0.0, (1 - usage.total_tokens / t.token_limit) * 100)
            results.append({
                "id": t.id,
                "agent_type": t.agent_type.value,
                "label": t.label,
                "model": t.model,
                "is_primary": t.is_primary,
                "token_limit": t.token_limit,
                "enabled": t.enabled,
                "tokens_used": usage.total_tokens,
                "call_count": usage.call_count,
                "pct_free": round(pct_free, 1),
            })
        return results
    except Exception:
        return []


def get_agents_summary(conn) -> list[dict]:
    if conn is None:
        return []
    try:
        from ..workspace import get_active_agent_views

        views = get_active_agent_views(conn)

        # Ingress counts
        ingress_counts: dict[int, int] = {}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT agent_view_id, COUNT(*) AS cnt "
                    "FROM ingress_identity WHERE is_active = 1 "
                    "GROUP BY agent_view_id"
                )
                for row in cur.fetchall():
                    ingress_counts[row["agent_view_id"]] = row["cnt"]
        except Exception:
            pass

        # Build status
        build_status: dict[int, str] = {}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wb.agent_view_id, wb.status "
                    "FROM workspace_build wb "
                    "INNER JOIN ("
                    "  SELECT agent_view_id, MAX(created_at) AS max_created "
                    "  FROM workspace_build GROUP BY agent_view_id"
                    ") latest ON wb.agent_view_id = latest.agent_view_id "
                    "AND wb.created_at = latest.max_created"
                )
                for row in cur.fetchall():
                    build_status[row["agent_view_id"]] = row["status"]
        except Exception:
            pass

        # Workspace labels
        ws_labels: dict[int, str] = {}
        ws_ids = {av.workspace_id for av in views}
        if ws_ids:
            try:
                with conn.cursor() as cur:
                    placeholders = ",".join(["%s"] * len(ws_ids))
                    cur.execute(
                        f"SELECT id, code FROM workspace WHERE id IN ({placeholders})",
                        tuple(ws_ids),
                    )
                    for row in cur.fetchall():
                        ws_labels[row["id"]] = row["code"]
            except Exception:
                pass

        results = []
        for av in views:
            results.append({
                "id": av.id,
                "code": av.code,
                "label": av.label,
                "workspace_code": ws_labels.get(av.workspace_id, ""),
                "ingress_count": ingress_counts.get(av.id, 0),
                "build_status": build_status.get(av.id, "none"),
            })
        return results
    except Exception:
        return []


_module_schema_cache: list[ModuleSchema] | None = None


def get_module_schemas() -> list[ModuleSchema]:
    global _module_schema_cache
    if _module_schema_cache is not None:
        return _module_schema_cache

    from ..bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR
    from ..module_loader import scan_modules

    schemas: list[ModuleSchema] = []
    for modules_dir in (CORE_MODULES_DIR, USER_MODULES_DIR):
        if not Path(modules_dir).is_dir():
            continue
        try:
            manifests = scan_modules(modules_dir)
        except Exception:
            continue
        for m in manifests:
            if not m.config and not m.tools:
                continue
            tool_fields: dict = {}
            for tool in m.tools:
                tool_name = tool.get("name", "")
                fields = tool.get("fields", {})
                if fields:
                    tool_fields[tool_name] = fields
            schemas.append(ModuleSchema(
                name=m.name,
                fields=dict(m.config),
                tools=tool_fields,
            ))

    _module_schema_cache = schemas
    return schemas


def get_resolved_fields(conn, module: str, scope: str = "default", scope_id: int = 0) -> list[ResolvedField]:
    schemas = get_module_schemas()
    target = None
    for s in schemas:
        if s.name == module:
            target = s
            break
    if target is None:
        return []

    from ..bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR
    from ..config_resolver import _db_path, _env_key, read_config_defaults
    from ..module_loader import scan_modules
    from ..scoped_config import build_scoped_overrides, load_scoped_db_overrides

    module_path = None
    for modules_dir in (CORE_MODULES_DIR, USER_MODULES_DIR):
        if not Path(modules_dir).is_dir():
            continue
        try:
            for m in scan_modules(modules_dir):
                if m.name == module:
                    module_path = m.path
                    break
        except Exception:
            continue
        if module_path:
            break

    config_defaults = read_config_defaults(module_path) if module_path else {}

    # Load scoped overrides and per-scope overrides for source detection
    if scope == "agent_view":
        # Need workspace_id for scoped resolution
        ws_id = None
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT workspace_id FROM agent_view WHERE id = %s", (scope_id,))
                    row = cur.fetchone()
                    if row:
                        ws_id = row["workspace_id"]
            except Exception:
                pass
        merged_overrides = build_scoped_overrides(conn, agent_view_id=scope_id, workspace_id=ws_id)
        scope_overrides = load_scoped_db_overrides(conn, scope, scope_id)
    elif scope == "workspace":
        merged_overrides = build_scoped_overrides(conn, workspace_id=scope_id)
        scope_overrides = load_scoped_db_overrides(conn, scope, scope_id)
    else:
        from ..config_resolver import load_db_overrides
        merged_overrides = load_db_overrides(conn)
        scope_overrides = merged_overrides

    results: list[ResolvedField] = []
    for field_name, field_schema in target.fields.items():
        field_type = field_schema.get("type", "string")
        label = field_schema.get("label", field_name)
        obscure = field_type == "obscure"
        db_path = _db_path(module, field_name)
        env_key = _env_key(module, field_name)

        # Determine source
        env_val = os.environ.get(env_key)
        if env_val is not None:
            source = "env"
            value = env_val
        elif db_path in scope_overrides:
            source = "db"
            value = scope_overrides[db_path][0]
        elif db_path in merged_overrides:
            source = "db:inherited"
            value = merged_overrides[db_path][0]
        elif field_name in config_defaults:
            source = "json"
            value = str(config_defaults[field_name])
        else:
            source = "none"
            value = None

        display_value = "****" if obscure and value else (value if value is not None else "")
        results.append(ResolvedField(
            path=f"{module}/{field_name}",
            field_name=field_name,
            value=value,
            display_value=display_value,
            source=source,
            field_type=field_type,
            label=label,
            obscure=obscure,
        ))

    return results


def get_workspaces(conn) -> list[dict]:
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, code, label, is_active FROM workspace ORDER BY id")
            return cur.fetchall()
    except Exception:
        return []


def get_agent_views(conn, workspace_id: int | None = None) -> list[dict]:
    if conn is None:
        return []
    try:
        sql = "SELECT id, code, label, workspace_id, is_active FROM agent_view"
        params: list = []
        if workspace_id is not None:
            sql += " WHERE workspace_id = %s"
            params.append(workspace_id)
        sql += " ORDER BY id"
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:
        return []


def set_config_value(conn, path: str, value: str, scope: str = "default", scope_id: int = 0) -> None:
    from ..core_config import config_set_auto_encrypt

    config_set_auto_encrypt(conn, path, value, scope=scope, scope_id=scope_id)
    conn.commit()


def delete_config_override(conn, path: str, scope: str = "default", scope_id: int = 0) -> bool:
    from ..core_config import config_delete

    result = config_delete(conn, path, scope=scope, scope_id=scope_id)
    conn.commit()
    return result


def do_set_primary_token(conn, agent_type: str, token_id: int) -> bool:
    from ..agent_manager.models import AgentProvider
    from ..agent_manager.token_store import set_primary_token

    provider = AgentProvider(agent_type)
    result = set_primary_token(conn, provider, token_id)
    conn.commit()
    return result


def do_deregister_token(conn, token_id: int) -> bool:
    from ..agent_manager.token_store import deregister_token

    result = deregister_token(conn, token_id)
    conn.commit()
    return result
