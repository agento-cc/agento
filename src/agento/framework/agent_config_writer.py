"""Generate agent CLI config files from resolved scoped config.

Before each worker run, generates native config files that agent CLIs expect:
  - .claude.json (Claude Code project config)
  - .claude/settings.json (Claude Code user settings)
  - .mcp.json (MCP server configuration)
  - .codex/config.toml (Codex CLI config)

Config field paths follow the convention:
  agent_view/claude/model          -> model for Claude CLI
  agent_view/claude/personality    -> system prompt / personality
  agent_view/mcp/servers           -> MCP server definitions (JSON)
  agent_view/codex/model           -> model for Codex CLI
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Config path prefix for agent CLI settings
AGENT_CONFIG_PREFIX = "agent_view/"


def _get_agent_config(resolved_config: dict[str, tuple[str, bool]]) -> dict[str, str]:
    """Extract agent_view/* paths from resolved DB overrides into a flat dict.

    Returns {relative_path: value}, e.g. {"claude/model": "opus-4"}.
    """
    result = {}
    for path, (value, _encrypted) in resolved_config.items():
        if path.startswith(AGENT_CONFIG_PREFIX) and value is not None:
            relative = path[len(AGENT_CONFIG_PREFIX):]
            result[relative] = value
    return result


def generate_claude_config(working_dir: Path, agent_config: dict[str, str]) -> None:
    """Generate .claude.json and .claude/settings.json in the working directory."""
    # .claude.json — project-level config
    claude_json: dict[str, Any] = {}

    model = agent_config.get("claude/model")
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

    # .claude/settings.json — user-level settings
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


def _inject_agent_view_id(servers: dict, agent_view_id: int) -> dict:
    """Append ?agent_view_id=N to toolbox SSE/MCP URLs in mcpServers config."""
    for server_cfg in servers.values():
        url = server_cfg.get("url", "")
        if "/sse" in url or "/mcp" in url:
            sep = "&" if "?" in url else "?"
            server_cfg["url"] = f"{url}{sep}agent_view_id={agent_view_id}"
    return servers


def generate_mcp_config(
    working_dir: Path,
    agent_config: dict[str, str],
    *,
    agent_view_id: int | None = None,
) -> None:
    """Generate .mcp.json in the working directory."""
    servers_raw = agent_config.get("mcp/servers")
    if not servers_raw:
        return

    try:
        servers = json.loads(servers_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid JSON in agent_view/mcp/servers, skipping .mcp.json generation")
        return

    if agent_view_id is not None:
        servers = _inject_agent_view_id(servers, agent_view_id)

    mcp_config = {"mcpServers": servers}
    config_path = working_dir / ".mcp.json"
    config_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
    logger.debug("Generated %s", config_path)


def generate_codex_config(working_dir: Path, agent_config: dict[str, str]) -> None:
    """Generate .codex/config.toml in the working directory."""
    lines: list[str] = []

    model = agent_config.get("codex/model")
    if model:
        lines.append(f'model = "{model}"')

    approval_mode = agent_config.get("codex/approval_mode")
    if approval_mode:
        lines.append(f'approval_mode = "{approval_mode}"')

    if not lines:
        return

    codex_dir = working_dir / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text("\n".join(lines) + "\n")
    logger.debug("Generated %s", config_path)


def populate_agent_configs(
    working_dir: str | Path,
    scoped_overrides: dict[str, tuple[str, bool]],
    *,
    agent_view_id: int | None = None,
) -> None:
    """Generate all agent CLI config files from scoped DB overrides.

    Called before each worker run with the merged (agent_view -> workspace -> global) overrides.
    """
    wd = Path(working_dir)
    wd.mkdir(parents=True, exist_ok=True)

    agent_config = _get_agent_config(scoped_overrides)

    if not agent_config:
        logger.debug("No agent_view/* config paths found, skipping config file generation")
        return

    generate_claude_config(wd, agent_config)
    generate_mcp_config(wd, agent_config, agent_view_id=agent_view_id)
    generate_codex_config(wd, agent_config)

    logger.info("Populated agent config files in %s", wd)
