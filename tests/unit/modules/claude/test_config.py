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

        writer.inject_runtime_params(
            work_dir, job_id=10, workspace_code="acme", agent_view_code="dev",
        )

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == (
            "http://toolbox:3001/sse?agent_view_id=2&job_id=10&ws=acme&av=dev"
        )

    def test_noop_when_no_mcp_json(self, writer, work_dir):
        writer.inject_runtime_params(
            work_dir, job_id=10, workspace_code="acme", agent_view_code="dev",
        )
        assert not (work_dir / ".mcp.json").exists()

    def test_handles_mcp_url(self, writer, work_dir):
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/mcp?agent_view_id=2"}}}
        (work_dir / ".mcp.json").write_text(json.dumps(mcp))

        writer.inject_runtime_params(
            work_dir, job_id=5, workspace_code="ws", agent_view_code="av",
        )

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "job_id=5&ws=ws&av=av" in data["mcpServers"]["toolbox"]["url"]
