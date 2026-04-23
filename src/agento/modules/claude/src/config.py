"""Claude Code CLI config writer — .claude.json, .claude/settings.json, .mcp.json."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        logger.warning("Failed to parse JSON config at %s", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _merge_json(legacy: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(legacy)
    for key, value in current.items():
        if key == "enabledMcpjsonServers":
            legacy_list = legacy.get(key, [])
            current_list = value
            if isinstance(legacy_list, list) and isinstance(current_list, list):
                merged[key] = list(dict.fromkeys([*legacy_list, *current_list]))
                continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_json(merged[key], value)
        else:
            merged[key] = value
    return merged


class ClaudeConfigWriter:
    """Writes Claude Code CLI config files: .claude.json, .claude/settings.json, .mcp.json."""

    def owned_paths(self) -> tuple[set[str], set[str]]:
        return {".claude.json", ".mcp.json"}, {".claude"}

    def persistent_home_paths(self) -> list[str]:
        """Claude Code session + todo state that must survive workspace rebuilds."""
        return [".claude/projects", ".claude/todos"]

    def write_credentials(self, build_dir: Path, credentials: dict) -> None:
        """Materialize Claude Code's full login state into ``build_dir``.

        Writes ``.claude/.credentials.json`` (oauth tokens) and merges Claude's
        captured ``~/.claude.json`` into ``build_dir/.claude.json`` (so Claude
        sees ``oauthAccount`` and considers itself logged in on first run).
        Preserves any agent_view-level keys already in ``.claude.json`` such as
        ``model``/``systemPrompt``/``permissions`` written by ``prepare_workspace``.
        """
        raw_auth = credentials.get("raw_auth") or {}
        raw_creds = raw_auth.get("credentials") if isinstance(raw_auth, dict) else None
        claude_oauth = (raw_creds or {}).get("claudeAiOauth") if isinstance(raw_creds, dict) else None

        if isinstance(claude_oauth, dict) and claude_oauth.get("accessToken"):
            # Preferred: write back Claude's full payload verbatim so fields like
            # ``scopes`` and ``rateLimitTier`` survive. Anything less trips Claude
            # into the login picker even with a valid accessToken.
            creds_payload = raw_creds
        else:
            # Backwards compat for tokens stored before raw_auth capture, and for
            # file-based ``token:register`` using the legacy 4-field schema.
            access_token = credentials.get("subscription_key")
            if not access_token:
                return
            creds_payload = {
                "claudeAiOauth": {
                    "accessToken": access_token,
                    "refreshToken": credentials.get("refresh_token"),
                    "expiresAt": credentials.get("expires_at"),
                    "subscriptionType": credentials.get("subscription_type"),
                }
            }

        claude_dir = build_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        creds_path = claude_dir / ".credentials.json"
        creds_path.write_text(json.dumps(creds_payload, indent=2))
        os.chmod(creds_path, 0o600)
        logger.debug("Wrote Claude credentials to %s", creds_path)

        claude_json_payload = raw_auth.get("claude_json") if isinstance(raw_auth, dict) else None
        if isinstance(claude_json_payload, dict) and claude_json_payload:
            claude_json_path = build_dir / ".claude.json"
            existing: dict[str, Any] = {}
            if claude_json_path.is_file():
                try:
                    parsed = json.loads(claude_json_path.read_text())
                    if isinstance(parsed, dict):
                        existing = parsed
                except (json.JSONDecodeError, OSError):
                    existing = {}
            # Auth state wins over prior build contents for any Claude-managed
            # keys (``oauthAccount``, ``userID``, ``numStartups``, ...); agent_view
            # config keys like ``model`` / ``systemPrompt`` / ``permissions`` that
            # only ``prepare_workspace`` sets survive automatically because they
            # are not present in ``claude_json_payload``.
            merged = {**existing, **claude_json_payload}
            claude_json_path.write_text(json.dumps(merged, indent=2))
            logger.debug("Wrote Claude user state to %s", claude_json_path)

    def migrate_legacy_workspace_config(self, build_dir: Path, workspace_root: Path) -> None:
        """Merge legacy shared-HOME Claude config into the per-agent build."""
        legacy_files = [
            ".claude.json",
            ".mcp.json",
            ".claude/settings.json",
            ".claude/settings.local.json",
        ]
        for rel in legacy_files:
            legacy_path = workspace_root / rel
            if not legacy_path.is_file():
                continue
            build_path = build_dir / rel
            build_path.parent.mkdir(parents=True, exist_ok=True)
            if not build_path.is_file():
                build_path.write_text(legacy_path.read_text())
                continue
            merged = _merge_json(_load_json(legacy_path), _load_json(build_path))
            build_path.write_text(json.dumps(merged, indent=2) + "\n")

    def prepare_workspace(
        self,
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
        toolbox_url: str,
    ) -> None:
        working_dir.mkdir(parents=True, exist_ok=True)
        self._write_claude_json(working_dir, agent_config)
        self._write_settings_json(working_dir, agent_config)
        self._write_mcp_json(
            working_dir, agent_config,
            agent_view_id=agent_view_id,
            toolbox_url=toolbox_url,
        )

    def inject_runtime_params(
        self,
        artifacts_dir: Path,
        *,
        job_id: int,
    ) -> None:
        mcp_path = artifacts_dir / ".mcp.json"
        if not mcp_path.is_file():
            return
        try:
            data = json.loads(mcp_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        servers = data.get("mcpServers", {})
        for server_cfg in servers.values():
            url = server_cfg.get("url", "")
            if "/sse" in url or "/mcp" in url:
                sep = "&" if "?" in url else "?"
                server_cfg["url"] = f"{url}{sep}job_id={job_id}"
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
        toolbox_url: str,
    ) -> None:
        # Auto-inject the toolbox MCP entry; operators can add more (or shadow
        # "toolbox") via agent_view/mcp/servers.
        servers: dict[str, dict] = {
            "toolbox": {"url": f"{toolbox_url.rstrip('/')}/sse"},
        }
        extra_raw = agent_config.get("mcp/servers")
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    servers.update(extra)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON in agent_view/mcp/servers, ignoring extras")

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
