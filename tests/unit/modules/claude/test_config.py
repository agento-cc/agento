"""Tests for ClaudeConfigWriter — .claude.json, .claude/settings.json, .mcp.json."""
from __future__ import annotations

import json

import pytest

from agento.modules.claude.src.config import ClaudeConfigWriter


@pytest.fixture
def writer():
    return ClaudeConfigWriter()


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "workspace" / "main" / "alpha"
    d.mkdir(parents=True)
    return d


class TestPrepareWorkspace:
    def test_generates_claude_json_with_model(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "opus-4"})
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["model"] == "opus-4"

    def test_generates_system_prompt(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "sonnet", "claude/personality": "Be concise."})
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["systemPrompt"] == "Be concise."

    def test_generates_permissions(self, writer, work_dir):
        perms = '{"allow": ["Read", "Write"]}'
        writer.prepare_workspace(work_dir, {"claude/permissions": perms})
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["permissions"] == {"allow": ["Read", "Write"]}

    def test_skips_invalid_permissions_json(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "opus", "claude/permissions": "not-json{"})
        data = json.loads((work_dir / ".claude.json").read_text())
        assert "permissions" not in data

    def test_generates_settings_json_full_trust(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"claude/trust_level": "full"})
        settings_path = work_dir / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is True

    def test_trust_level_not_full(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"claude/trust_level": "limited"})
        data = json.loads((work_dir / ".claude" / "settings.json").read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is False

    def test_no_config_no_files(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {})
        assert not (work_dir / ".claude.json").exists()
        assert not (work_dir / ".claude" / "settings.json").exists()

    def test_generates_mcp_json(self, writer, work_dir):
        servers = '{"toolbox": {"command": "npx", "args": ["-y", "server"]}}'
        writer.prepare_workspace(work_dir, {"mcp/servers": servers})
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "toolbox" in data["mcpServers"]

    def test_skips_mcp_when_no_servers(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "opus"})
        assert not (work_dir / ".mcp.json").exists()

    def test_skips_mcp_invalid_json(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"mcp/servers": "not-json{"})
        assert not (work_dir / ".mcp.json").exists()

    def test_appends_agent_view_id_to_sse_url(self, writer, work_dir):
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        writer.prepare_workspace(work_dir, {"mcp/servers": servers}, agent_view_id=2)
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse?agent_view_id=2"

    def test_no_agent_view_id_leaves_url_unchanged(self, writer, work_dir):
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        writer.prepare_workspace(work_dir, {"mcp/servers": servers})
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_does_not_modify_non_mcp_urls(self, writer, work_dir):
        servers = '{"other": {"type": "stdio", "command": "node"}}'
        writer.prepare_workspace(work_dir, {"mcp/servers": servers}, agent_view_id=5)
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "url" not in data["mcpServers"]["other"]

    def test_injects_into_any_sse_or_mcp_url(self, writer, work_dir):
        servers = '{"other": {"type": "sse", "url": "http://other:4000/sse"}}'
        writer.prepare_workspace(work_dir, {"mcp/servers": servers}, agent_view_id=5)
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "agent_view_id=5" in data["mcpServers"]["other"]["url"]


class TestInjectRuntimeParams:
    def test_appends_params_to_mcp_json(self, writer, work_dir):
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/sse?agent_view_id=2"}}}
        (work_dir / ".mcp.json").write_text(json.dumps(mcp))

        writer.inject_runtime_params(work_dir, job_id=10)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == (
            "http://toolbox:3001/sse?agent_view_id=2&job_id=10"
        )

    def test_noop_when_no_mcp_json(self, writer, work_dir):
        writer.inject_runtime_params(work_dir, job_id=10)
        assert not (work_dir / ".mcp.json").exists()

    def test_handles_mcp_url(self, writer, work_dir):
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/mcp?agent_view_id=2"}}}
        (work_dir / ".mcp.json").write_text(json.dumps(mcp))

        writer.inject_runtime_params(work_dir, job_id=5)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "job_id=5" in data["mcpServers"]["toolbox"]["url"]


class TestWriteCredentials:
    def test_writes_credentials_json_in_claude_ai_oauth_format(self, writer, work_dir):
        creds = {
            "subscription_key": "sk-ant-oat01-xyz",
            "refresh_token": "rt-123",
            "expires_at": 1799999999,
            "subscription_type": "team",
            "id_token": "ignored",
            "raw_auth": "ignored",
        }
        writer.write_credentials(work_dir, creds)

        path = work_dir / ".claude" / ".credentials.json"
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data == {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-xyz",
                "refreshToken": "rt-123",
                "expiresAt": 1799999999,
                "subscriptionType": "team",
            }
        }
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_skips_when_no_subscription_key(self, writer, work_dir):
        writer.write_credentials(work_dir, {"refresh_token": "x"})
        assert not (work_dir / ".claude" / ".credentials.json").exists()

    def test_optional_fields_become_null(self, writer, work_dir):
        writer.write_credentials(work_dir, {"subscription_key": "sk-x"})
        data = json.loads((work_dir / ".claude" / ".credentials.json").read_text())
        oauth = data["claudeAiOauth"]
        assert oauth["accessToken"] == "sk-x"
        assert oauth["refreshToken"] is None
        assert oauth["expiresAt"] is None
        assert oauth["subscriptionType"] is None


class TestOwnedPaths:
    def test_returns_claude_files_and_dir(self, writer):
        files, dirs = writer.owned_paths()
        assert files == {".claude.json", ".mcp.json"}
        assert dirs == {".claude"}


class TestMigrateLegacyWorkspaceConfig:
    def test_merges_enabled_mcp_servers_from_legacy_settings_local(self, writer, work_dir, tmp_path):
        build_settings_dir = work_dir / ".claude"
        build_settings_dir.mkdir(parents=True)
        (build_settings_dir / "settings.local.json").write_text(
            json.dumps({"enabledMcpjsonServers": ["other"]})
        )

        workspace_root = tmp_path / "workspace"
        legacy_settings_dir = workspace_root / ".claude"
        legacy_settings_dir.mkdir(parents=True)
        (legacy_settings_dir / "settings.local.json").write_text(
            json.dumps({"enabledMcpjsonServers": ["toolbox"]})
        )

        writer.migrate_legacy_workspace_config(work_dir, workspace_root)

        data = json.loads((build_settings_dir / "settings.local.json").read_text())
        assert data["enabledMcpjsonServers"] == ["toolbox", "other"]
