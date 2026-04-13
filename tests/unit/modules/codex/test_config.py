"""Tests for CodexConfigWriter — .codex/config.toml with MCP servers."""
from __future__ import annotations

import tomllib

import pytest

from agento.modules.codex.src.config import CodexConfigWriter


@pytest.fixture
def writer():
    return CodexConfigWriter()


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "workspace" / "main" / "dev"
    d.mkdir(parents=True)
    return d


class TestPrepareWorkspace:
    def test_writes_model(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "o3"})
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert 'model = "o3"' in content

    def test_writes_approval_mode(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "o3", "codex/approval_mode": "full-auto"})
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert 'approval_mode = "full-auto"' in content

    def test_writes_mcp_servers_sse(self, writer, work_dir):
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        writer.prepare_workspace(
            work_dir, {"model": "o3", "mcp/servers": servers}, agent_view_id=2,
        )
        config_path = work_dir / ".codex" / "config.toml"
        data = tomllib.loads(config_path.read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "sse"
        assert "agent_view_id=2" in data["mcp_servers"]["toolbox"]["url"]

    def test_writes_mcp_servers_streamable_http(self, writer, work_dir):
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/mcp"}}'
        writer.prepare_workspace(
            work_dir, {"model": "o3", "mcp/servers": servers}, agent_view_id=3,
        )
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "streamable_http"
        assert "agent_view_id=3" in data["mcp_servers"]["toolbox"]["url"]

    def test_no_agent_view_id_leaves_url_unchanged(self, writer, work_dir):
        servers = '{"toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"}}'
        writer.prepare_workspace(work_dir, {"model": "o3", "mcp/servers": servers})
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_no_config_no_files(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {})
        assert not (work_dir / ".codex" / "config.toml").exists()

    def test_skips_invalid_servers_json(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "o3", "mcp/servers": "not-json{"})
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert "mcp_servers" not in content

    def test_multiple_servers(self, writer, work_dir):
        import json
        servers = json.dumps({
            "toolbox": {"type": "sse", "url": "http://toolbox:3001/sse"},
            "other": {"type": "sse", "url": "http://other:4000/mcp"},
        })
        writer.prepare_workspace(work_dir, {"mcp/servers": servers}, agent_view_id=1)
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "sse"
        assert data["mcp_servers"]["other"]["type"] == "streamable_http"


class TestInjectRuntimeParams:
    def test_appends_params_to_toml_urls(self, writer, work_dir):
        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        (codex_dir / "config.toml").write_text(
            'model = "o3"\n'
            "\n[mcp_servers.toolbox]\n"
            'type = "sse"\n'
            'url = "http://toolbox:3001/sse?agent_view_id=2"\n'
        )

        writer.inject_runtime_params(work_dir, job_id=10)

        data = tomllib.loads((codex_dir / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["url"] == (
            "http://toolbox:3001/sse?agent_view_id=2&job_id=10"
        )

    def test_noop_when_no_config_toml(self, writer, work_dir):
        writer.inject_runtime_params(work_dir, job_id=10)
        assert not (work_dir / ".codex" / "config.toml").exists()

    def test_preserves_model_and_approval_mode(self, writer, work_dir):
        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        (codex_dir / "config.toml").write_text(
            'model = "gpt-5"\n'
            'approval_mode = "full-auto"\n'
            "\n[mcp_servers.toolbox]\n"
            'type = "sse"\n'
            'url = "http://toolbox:3001/sse?agent_view_id=1"\n'
        )

        writer.inject_runtime_params(work_dir, job_id=5)

        data = tomllib.loads((codex_dir / "config.toml").read_text())
        assert data["model"] == "gpt-5"
        assert data["approval_mode"] == "full-auto"
        assert "job_id=5" in data["mcp_servers"]["toolbox"]["url"]


class TestOwnedPaths:
    def test_returns_codex_dir(self, writer):
        files, dirs = writer.owned_paths()
        assert files == set()
        assert dirs == {".codex"}
