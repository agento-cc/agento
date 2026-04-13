"""Claude Code CLI config writer — .claude.json, .claude/settings.json, .mcp.json."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ClaudeConfigWriter:
    """Writes Claude Code CLI config files: .claude.json, .claude/settings.json, .mcp.json."""

    def owned_paths(self) -> tuple[set[str], set[str]]:
        return {".claude.json", ".mcp.json"}, {".claude"}

    def prepare_workspace(
        self,
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
    ) -> None:
        working_dir.mkdir(parents=True, exist_ok=True)
        self._write_claude_json(working_dir, agent_config)
        self._write_settings_json(working_dir, agent_config)
        self._write_mcp_json(working_dir, agent_config, agent_view_id=agent_view_id)

    def inject_runtime_params(
        self,
        run_dir: Path,
        *,
        job_id: int,
        workspace_code: str,
        agent_view_code: str,
    ) -> None:
        mcp_path = run_dir / ".mcp.json"
        if not mcp_path.is_file():
            return
        try:
            data = json.loads(mcp_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        servers = data.get("mcpServers", {})
        extra = f"job_id={job_id}&ws={workspace_code}&av={agent_view_code}"
        for server_cfg in servers.values():
            url = server_cfg.get("url", "")
            if "/sse" in url or "/mcp" in url:
                sep = "&" if "?" in url else "?"
                server_cfg["url"] = f"{url}{sep}{extra}"
        mcp_path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _write_claude_json(working_dir: Path, agent_config: dict[str, str]) -> None:
        claude_json: dict[str, Any] = {}

        model = agent_config.get("model")
        if model:
            claude_json["model"] = model

        personality = agent_config.get("claude/personality")
        if personality:
            claude_json["systemPrompt"] = personality

        permissions = agent_config.get("claude/permissions")
        if permissions:
            try:
                claude_json["permissions"] = json.loads(permissions)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON in agent_view/claude/permissions, skipping")

        if claude_json:
            config_path = working_dir / ".claude.json"
            config_path.write_text(json.dumps(claude_json, indent=2) + "\n")
            logger.debug("Generated %s", config_path)

    @staticmethod
    def _write_settings_json(working_dir: Path, agent_config: dict[str, str]) -> None:
        settings: dict[str, Any] = {}

        trust_level = agent_config.get("claude/trust_level")
        if trust_level:
            settings["permissions"] = {"dangerouslySkipPermissions": trust_level == "full"}

        if settings:
            settings_dir = working_dir / ".claude"
            settings_dir.mkdir(parents=True, exist_ok=True)
            settings_path = settings_dir / "settings.json"
            settings_path.write_text(json.dumps(settings, indent=2) + "\n")
            logger.debug("Generated %s", settings_path)

    @staticmethod
    def _write_mcp_json(
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
    ) -> None:
        servers_raw = agent_config.get("mcp/servers")
        if not servers_raw:
            return

        try:
            servers = json.loads(servers_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid JSON in agent_view/mcp/servers, skipping .mcp.json generation")
            return

        if agent_view_id is not None:
            for server_cfg in servers.values():
                url = server_cfg.get("url", "")
                if "/sse" in url or "/mcp" in url:
                    sep = "&" if "?" in url else "?"
                    server_cfg["url"] = f"{url}{sep}agent_view_id={agent_view_id}"

        mcp_config = {"mcpServers": servers}
        config_path = working_dir / ".mcp.json"
        config_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
        logger.debug("Generated %s", config_path)
