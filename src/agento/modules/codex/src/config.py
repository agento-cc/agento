"""Codex CLI config writer — .codex/config.toml with MCP servers."""
from __future__ import annotations

import json
import logging
import os
import re
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)


def _derive_mcp_type(url: str) -> str:
    """Derive MCP server type from URL path."""
    if "/mcp" in url:
        return "streamable_http"
    if "/sse" in url:
        return "sse"
    logger.warning("Cannot derive MCP type from URL %r, falling back to sse", url)
    return "sse"


_BARE_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge TOML-like nested dicts, with override winning."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _toml_quote_key(key: str) -> str:
    if _BARE_TOML_KEY_RE.match(key):
        return key
    return json.dumps(key)


def _toml_literal(value: str | bool | int | float) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _dump_toml(data: dict) -> str:
    """Serialize the small TOML subset used by Codex config files."""
    lines: list[str] = []

    def emit_table(table: dict, path: tuple[str, ...]) -> None:
        scalar_keys = sorted(k for k, v in table.items() if not isinstance(v, dict))
        child_keys = sorted(k for k, v in table.items() if isinstance(v, dict))

        if path:
            if lines and lines[-1] != "":
                lines.append("")
            header = ".".join(_toml_quote_key(part) for part in path)
            lines.append(f"[{header}]")

        for key in scalar_keys:
            lines.append(f"{_toml_quote_key(key)} = {_toml_literal(table[key])}")

        for key in child_keys:
            emit_table(table[key], (*path, key))

    root_scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    root_tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for key in sorted(root_scalars):
        lines.append(f"{_toml_quote_key(key)} = {_toml_literal(root_scalars[key])}")
    for key in sorted(root_tables):
        emit_table(root_tables[key], (key,))
    return "\n".join(lines) + ("\n" if lines else "")


class CodexConfigWriter:
    """Writes Codex CLI config: .codex/config.toml with MCP servers block."""

    def owned_paths(self) -> tuple[set[str], set[str]]:
        return set(), {".codex"}

    def persistent_home_paths(self) -> list[str]:
        """Codex session + history state that must survive workspace rebuilds."""
        return [".codex/history.jsonl", ".codex/sessions"]

    def write_credentials(self, build_dir: Path, credentials: dict) -> None:
        """Write Codex CLI's ``.codex/auth.json`` (raw auth payload captured at login)."""
        raw_auth = credentials.get("raw_auth")
        if not raw_auth:
            logger.warning(
                "Codex credentials missing raw_auth; skipping .codex/auth.json materialization "
                "— agent will need to /login on first run."
            )
            return
        codex_dir = build_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        path = codex_dir / "auth.json"
        path.write_text(json.dumps(raw_auth, indent=2))
        os.chmod(path, 0o600)
        logger.debug("Wrote Codex credentials to %s", path)

    def migrate_legacy_workspace_config(self, build_dir: Path, workspace_root: Path) -> None:
        """Merge legacy shared-HOME ``workspace/.codex/config.toml`` into the build.

        The per-agent HOME migration stopped Codex from seeing MCP servers stored in
        the old shared workspace config. Preserve those entries in the new build so
        existing installs keep working until everything is moved to scoped DB config.
        """
        legacy_path = workspace_root / ".codex" / "config.toml"
        if not legacy_path.is_file():
            return

        try:
            legacy_data = tomllib.loads(legacy_path.read_text())
        except Exception:
            logger.warning("Failed to parse legacy Codex config at %s", legacy_path, exc_info=True)
            return

        codex_dir = build_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        build_path = codex_dir / "config.toml"
        if build_path.is_file():
            try:
                build_data = tomllib.loads(build_path.read_text())
            except Exception:
                logger.warning("Failed to parse build Codex config at %s", build_path, exc_info=True)
                build_data = {}
        else:
            build_data = {}

        merged = _deep_merge(legacy_data, build_data)
        build_path.write_text(_dump_toml(merged))
        logger.debug("Merged legacy Codex config from %s into %s", legacy_path, build_path)

    def prepare_workspace(
        self,
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
        toolbox_url: str,
    ) -> None:
        lines: list[str] = []

        model = agent_config.get("model")
        if model:
            lines.append(f'model = "{model}"')

        approval_mode = agent_config.get("codex/approval_mode")
        if approval_mode:
            lines.append(f'approval_mode = "{approval_mode}"')

        # Auto-inject the toolbox MCP entry; operators can add more (or shadow
        # "toolbox") via agent_view/mcp/servers.
        servers: dict[str, dict] = {
            "toolbox": {"url": f"{toolbox_url.rstrip('/')}/mcp"},
        }
        extra_raw = agent_config.get("mcp/servers")
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    servers.update(extra)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON in agent_view/mcp/servers, ignoring extras")

        for name, server_cfg in servers.items():
            url = server_cfg.get("url", "")
            if agent_view_id is not None and ("/sse" in url or "/mcp" in url):
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}agent_view_id={agent_view_id}"
            mcp_type = _derive_mcp_type(url)
            lines.append(f"\n[mcp_servers.{name}]")
            lines.append(f'type = "{mcp_type}"')
            lines.append(f'url = "{url}"')

        codex_dir = working_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text("\n".join(lines) + "\n")
        logger.debug("Generated %s", config_path)

    def inject_runtime_params(
        self,
        artifacts_dir: Path,
        *,
        job_id: int,
    ) -> None:
        config_path = artifacts_dir / ".codex" / "config.toml"
        if not config_path.is_file():
            return
        try:
            data = tomllib.loads(config_path.read_text())
        except Exception:
            return
        mcp_servers = data.get("mcp_servers", {})
        if not mcp_servers:
            return

        for server_cfg in mcp_servers.values():
            url = server_cfg.get("url", "")
            if "/sse" in url or "/mcp" in url:
                sep = "&" if "?" in url else "?"
                server_cfg["url"] = f"{url}{sep}job_id={job_id}"

        # Re-write the TOML (hand-written, simple structure)
        lines: list[str] = []
        model = data.get("model")
        if model:
            lines.append(f'model = "{model}"')
        approval_mode = data.get("approval_mode")
        if approval_mode:
            lines.append(f'approval_mode = "{approval_mode}"')

        for name, server_cfg in mcp_servers.items():
            lines.append(f"\n[mcp_servers.{name}]")
            lines.append(f'type = "{server_cfg.get("type", "sse")}"')
            lines.append(f'url = "{server_cfg.get("url", "")}"')

        config_path.write_text("\n".join(lines) + "\n")
