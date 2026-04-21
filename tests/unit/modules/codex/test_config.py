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
    TOOLBOX = "http://toolbox:3001"

    def test_writes_model(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "o3"}, toolbox_url=self.TOOLBOX)
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert 'model = "o3"' in content

    def test_writes_approval_mode(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"model": "o3", "codex/approval_mode": "full-auto"},
            toolbox_url=self.TOOLBOX,
        )
        content = (work_dir / ".codex" / "config.toml").read_text()
        assert 'approval_mode = "full-auto"' in content

    def test_user_can_shadow_toolbox_entry(self, writer, work_dir):
        servers = '{"toolbox": {"url": "http://toolbox:3001/sse"}}'
        writer.prepare_workspace(
            work_dir, {"model": "o3", "mcp/servers": servers},
            agent_view_id=2, toolbox_url=self.TOOLBOX,
        )
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "sse"
        assert "agent_view_id=2" in data["mcp_servers"]["toolbox"]["url"]

    def test_auto_injects_toolbox_streamable_http(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"model": "o3"},
            agent_view_id=3, toolbox_url=self.TOOLBOX,
        )
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "streamable_http"
        assert data["mcp_servers"]["toolbox"]["url"].startswith("http://toolbox:3001/mcp")
        assert "agent_view_id=3" in data["mcp_servers"]["toolbox"]["url"]

    def test_no_agent_view_id_leaves_url_unchanged(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "o3"}, toolbox_url=self.TOOLBOX)
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["url"] == "http://toolbox:3001/mcp"

    def test_empty_config_still_writes_toolbox_entry(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {}, toolbox_url=self.TOOLBOX)
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "streamable_http"

    def test_ignores_invalid_extras_json(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"model": "o3", "mcp/servers": "not-json{"},
            toolbox_url=self.TOOLBOX,
        )
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        # Toolbox is still auto-injected; bad extras are ignored.
        assert list(data["mcp_servers"].keys()) == ["toolbox"]

    def test_extras_merge_with_toolbox(self, writer, work_dir):
        import json
        extras = json.dumps({
            "other": {"url": "http://other:4000/mcp"},
        })
        writer.prepare_workspace(
            work_dir, {"mcp/servers": extras},
            agent_view_id=1, toolbox_url=self.TOOLBOX,
        )
        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["type"] == "streamable_http"
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


class TestWriteCredentials:
    def test_writes_auth_json_from_raw_auth(self, writer, work_dir):
        raw = {"tokens": {"access_token": "codex-access", "refresh_token": "codex-refresh"}}
        creds = {
            "subscription_key": "codex-access",
            "refresh_token": "codex-refresh",
            "expires_at": None,
            "subscription_type": None,
            "id_token": "idtok",
            "raw_auth": raw,
        }
        writer.write_credentials(work_dir, creds)

        path = work_dir / ".codex" / "auth.json"
        assert path.is_file()
        import json as _json
        assert _json.loads(path.read_text()) == raw
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_skips_without_raw_auth(self, writer, work_dir, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="agento.modules.codex.src.config"):
            writer.write_credentials(work_dir, {"subscription_key": "codex-access"})
        assert not (work_dir / ".codex" / "auth.json").exists()
        assert "raw_auth" in caplog.text


class TestOwnedPaths:
    def test_returns_codex_dir(self, writer):
        files, dirs = writer.owned_paths()
        assert files == set()
        assert dirs == {".codex"}


class TestMigrateLegacyWorkspaceConfig:
    def test_migrates_toolbox_mcp_from_legacy_workspace_codex_config(self, writer, work_dir, tmp_path):
        workspace_root = tmp_path / "workspace"
        legacy_codex = workspace_root / ".codex"
        legacy_codex.mkdir(parents=True)
        (legacy_codex / "config.toml").write_text(
            'model = "gpt-5.4"\n'
            "\n[mcp_servers.toolbox]\n"
            'type = "streamable_http"\n'
            'url = "http://toolbox:3001/mcp?agent_view_id=2"\n'
        )

        writer.migrate_legacy_workspace_config(work_dir, workspace_root)

        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["mcp_servers"]["toolbox"]["url"] == "http://toolbox:3001/mcp?agent_view_id=2"
        assert data["model"] == "gpt-5.4"

    def test_merges_legacy_mcp_with_existing_build_config(self, writer, work_dir, tmp_path):
        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        (codex_dir / "config.toml").write_text(
            'model = "gpt-5.4"\n'
            "\n[mcp_servers.other]\n"
            'type = "sse"\n'
            'url = "http://other:4000/sse"\n'
        )

        workspace_root = tmp_path / "workspace"
        legacy_codex = workspace_root / ".codex"
        legacy_codex.mkdir(parents=True)
        (legacy_codex / "config.toml").write_text(
            "\n[mcp_servers.toolbox]\n"
            'type = "streamable_http"\n'
            'url = "http://toolbox:3001/mcp?agent_view_id=2"\n'
        )

        writer.migrate_legacy_workspace_config(work_dir, workspace_root)

        data = tomllib.loads((work_dir / ".codex" / "config.toml").read_text())
        assert data["model"] == "gpt-5.4"
        assert data["mcp_servers"]["other"]["url"] == "http://other:4000/sse"
        assert data["mcp_servers"]["toolbox"]["url"] == "http://toolbox:3001/mcp?agent_view_id=2"
