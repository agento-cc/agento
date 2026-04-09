"""Tests for agent CLI config file generation."""
from __future__ import annotations

import json

import pytest

from agento.framework.agent_config_writer import (
    _get_agent_config,
    generate_claude_config,
    generate_codex_config,
    generate_mcp_config,
    populate_agent_configs,
)


@pytest.fixture
def work_dir(tmp_path):
    return tmp_path / "workspace" / "main" / "alpha"


class TestGetAgentConfig:
    def test_extracts_agent_prefix(self):
        overrides = {
            "agent_view/claude/model": ("opus-4", False),
            "agent_view/mcp/servers": ('{"toolbox": {}}', False),
            "jira/token": ("abc", False),
        }
        result = _get_agent_config(overrides)
        assert result == {
            "claude/model": "opus-4",
            "mcp/servers": '{"toolbox": {}}',
        }

    def test_skips_none_values(self):
        overrides = {"agent_view/claude/model": (None, False)}
        assert _get_agent_config(overrides) == {}

    def test_empty_overrides(self):
        assert _get_agent_config({}) == {}


class TestGenerateClaudeConfig:
    def test_generates_claude_json(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(work_dir, {"claude/model": "opus-4"})

        config_path = work_dir / ".claude.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["model"] == "opus-4"

    def test_generates_system_prompt(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(
            work_dir, {"claude/model": "sonnet", "claude/personality": "Be concise."}
        )
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["systemPrompt"] == "Be concise."

    def test_generates_permissions(self, work_dir):
        work_dir.mkdir(parents=True)
        perms = '{"allow": ["Read", "Write"]}'
        generate_claude_config(work_dir, {"claude/permissions": perms})
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["permissions"] == {"allow": ["Read", "Write"]}

    def test_skips_invalid_permissions_json(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(
            work_dir, {"claude/model": "opus", "claude/permissions": "not-json{"}
        )
        data = json.loads((work_dir / ".claude.json").read_text())
        assert "permissions" not in data

    def test_generates_settings_json(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(work_dir, {"claude/trust_level": "full"})
        settings_path = work_dir / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is True

    def test_trust_level_not_full(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(work_dir, {"claude/trust_level": "limited"})
        settings_path = work_dir / ".claude" / "settings.json"
        data = json.loads(settings_path.read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is False

    def test_no_config_no_files(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_claude_config(work_dir, {})
        assert not (work_dir / ".claude.json").exists()
        assert not (work_dir / ".claude" / "settings.json").exists()


class TestGenerateMcpConfig:
    def test_generates_mcp_json(self, work_dir):
        work_dir.mkdir(parents=True)
        servers = '{"toolbox": {"command": "npx", "args": ["-y", "server"]}}'
        generate_mcp_config(work_dir, {"mcp/servers": servers})

        config_path = work_dir / ".mcp.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "toolbox" in data["mcpServers"]

    def test_skips_when_no_servers(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_mcp_config(work_dir, {})
        assert not (work_dir / ".mcp.json").exists()

    def test_skips_invalid_json(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_mcp_config(work_dir, {"mcp/servers": "not-json{"})
        assert not (work_dir / ".mcp.json").exists()


    def test_appends_agent_view_id_to_toolbox_url(self, work_dir):
        work_dir.mkdir(parents=True)
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        generate_mcp_config(work_dir, {"mcp/servers": servers}, agent_view_id=2)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse?agent_view_id=2"

    def test_no_agent_view_id_leaves_url_unchanged(self, work_dir):
        work_dir.mkdir(parents=True)
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        generate_mcp_config(work_dir, {"mcp/servers": servers})

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_does_not_modify_non_mcp_urls(self, work_dir):
        work_dir.mkdir(parents=True)
        servers = '{"other": {"type": "stdio", "command": "node"}}'
        generate_mcp_config(work_dir, {"mcp/servers": servers}, agent_view_id=5)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "url" not in data["mcpServers"]["other"]

    def test_injects_into_any_sse_or_mcp_url(self, work_dir):
        work_dir.mkdir(parents=True)
        servers = '{"other": {"type": "sse", "url": "http://other:4000/sse"}}'
        generate_mcp_config(work_dir, {"mcp/servers": servers}, agent_view_id=5)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "agent_view_id=5" in data["mcpServers"]["other"]["url"]


class TestGenerateCodexConfig:
    def test_generates_config_toml(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_codex_config(work_dir, {"codex/model": "o3"})

        config_path = work_dir / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert 'model = "o3"' in content

    def test_approval_mode(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_codex_config(
            work_dir, {"codex/model": "o3", "codex/approval_mode": "full-auto"}
        )
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert 'approval_mode = "full-auto"' in content

    def test_no_config_no_files(self, work_dir):
        work_dir.mkdir(parents=True)
        generate_codex_config(work_dir, {})
        assert not (work_dir / ".codex" / "config.toml").exists()


class TestPopulateAgentConfigs:
    def test_creates_working_dir(self, tmp_path):
        wd = tmp_path / "new" / "deep" / "path"
        overrides = {"agent_view/claude/model": ("opus-4", False)}
        populate_agent_configs(wd, overrides)
        assert wd.exists()
        assert (wd / ".claude.json").exists()

    def test_generates_all_config_types(self, tmp_path):
        wd = tmp_path / "ws"
        overrides = {
            "agent_view/claude/model": ("opus-4", False),
            "agent_view/mcp/servers": ('{"toolbox": {"command": "node"}}', False),
            "agent_view/codex/model": ("o3", False),
        }
        populate_agent_configs(wd, overrides)
        assert (wd / ".claude.json").exists()
        assert (wd / ".mcp.json").exists()
        assert (wd / ".codex" / "config.toml").exists()

    def test_skips_when_no_agent_config(self, tmp_path):
        wd = tmp_path / "ws"
        overrides = {"jira/token": ("abc", False)}
        populate_agent_configs(wd, overrides)
        assert wd.exists()
        # No agent config files generated
        assert not (wd / ".claude.json").exists()
        assert not (wd / ".mcp.json").exists()

    def test_accepts_string_path(self, tmp_path):
        wd = str(tmp_path / "ws")
        overrides = {"agent_view/claude/model": ("sonnet", False)}
        populate_agent_configs(wd, overrides)
        assert (tmp_path / "ws" / ".claude.json").exists()

    def test_passes_agent_view_id_to_mcp_config(self, tmp_path):
        wd = tmp_path / "ws"
        overrides = {
            "agent_view/claude/model": ("opus-4", False),
            "agent_view/mcp/servers": ('{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}', False),
        }
        populate_agent_configs(wd, overrides, agent_view_id=3)
        data = json.loads((wd / ".mcp.json").read_text())
        assert "agent_view_id=3" in data["mcpServers"]["toolbox"]["url"]
