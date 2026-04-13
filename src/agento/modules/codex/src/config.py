"""Codex CLI config writer — .codex/config.toml with MCP servers."""
from __future__ import annotations

import json
import logging
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


class CodexConfigWriter:
    """Writes Codex CLI config: .codex/config.toml with MCP servers block."""

    def prepare_workspace(
        self,
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
    ) -> None:
        lines: list[str] = []

        model = agent_config.get("model")
        if model:
            lines.append(f'model = "{model}"')

        approval_mode = agent_config.get("codex/approval_mode")
        if approval_mode:
            lines.append(f'approval_mode = "{approval_mode}"')

        # MCP servers from agent_view/mcp/servers JSON
        servers_raw = agent_config.get("mcp/servers")
        if servers_raw:
            try:
                servers = json.loads(servers_raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON in agent_view/mcp/servers, skipping MCP servers in config.toml")
                servers = {}

            for name, server_cfg in servers.items():
                url = server_cfg.get("url", "")
                if agent_view_id is not None and ("/sse" in url or "/mcp" in url):
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}agent_view_id={agent_view_id}"
                mcp_type = _derive_mcp_type(url)
                lines.append(f"\n[mcp_servers.{name}]")
                lines.append(f'type = "{mcp_type}"')
                lines.append(f'url = "{url}"')

        if not lines:
            return

        codex_dir = working_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text("\n".join(lines) + "\n")
        logger.debug("Generated %s", config_path)

    def inject_runtime_params(
        self,
        run_dir: Path,
        *,
        job_id: int,
        workspace_code: str,
        agent_view_code: str,
    ) -> None:
        config_path = run_dir / ".codex" / "config.toml"
        if not config_path.is_file():
            return
        try:
            data = tomllib.loads(config_path.read_text())
        except Exception:
            return
        mcp_servers = data.get("mcp_servers", {})
        if not mcp_servers:
            return

        extra = f"job_id={job_id}&ws={workspace_code}&av={agent_view_code}"
        for server_cfg in mcp_servers.values():
            url = server_cfg.get("url", "")
            if "/sse" in url or "/mcp" in url:
                sep = "&" if "?" in url else "?"
                server_cfg["url"] = f"{url}{sep}{extra}"

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
