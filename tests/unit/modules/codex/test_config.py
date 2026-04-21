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


class TestCaptureRefreshedCredentials:
    def _make_token(self, refresh_token="tok-A", access_token="acc-A"):
        from unittest.mock import MagicMock
        from agento.framework.agent_manager.models import AgentProvider
        token = MagicMock()
        token.credentials = {
            "raw_auth": {"tokens": {"refresh_token": refresh_token, "access_token": access_token}},
            "refresh_token": refresh_token,
            "subscription_key": access_token,
        }
        token.agent_type = AgentProvider.CODEX
        token.label = "my-codex"
        token.token_limit = 0
        token.model = None
        return token

    def test_noop_when_no_auth_json(self, writer, work_dir):
        from unittest.mock import MagicMock, patch
        token = self._make_token()
        mock_conn = MagicMock()
        with patch("agento.modules.codex.src.config.register_token") as mock_reg:
            writer.capture_refreshed_credentials(work_dir, token, mock_conn)
        mock_reg.assert_not_called()

    def test_noop_when_refresh_token_unchanged(self, writer, work_dir):
        import json
        from unittest.mock import MagicMock, patch
        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        raw = {"tokens": {"refresh_token": "tok-A", "access_token": "acc-A"}}
        (codex_dir / "auth.json").write_text(json.dumps(raw))

        token = self._make_token(refresh_token="tok-A")
        with patch("agento.modules.codex.src.config.register_token") as mock_reg:
            writer.capture_refreshed_credentials(work_dir, token, MagicMock())
        mock_reg.assert_not_called()

    def test_upserts_db_when_refresh_token_changed(self, writer, work_dir):
        import json
        from unittest.mock import MagicMock, patch
        from agento.framework.agent_manager.models import AgentProvider

        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        refreshed = {"tokens": {"refresh_token": "tok-B", "access_token": "acc-B"}}
        (codex_dir / "auth.json").write_text(json.dumps(refreshed))

        token = self._make_token(refresh_token="tok-A")
        mock_conn = MagicMock()

        with patch("agento.modules.codex.src.config.register_token") as mock_reg:
            writer.capture_refreshed_credentials(work_dir, token, mock_conn)

        mock_reg.assert_called_once()
        call_args = mock_reg.call_args
        assert call_args[0][0] is mock_conn
        assert call_args[0][1] == AgentProvider.CODEX
        assert call_args[0][2] == "my-codex"
        saved_creds = call_args[0][3]
        assert saved_creds["raw_auth"] == refreshed
        assert saved_creds["refresh_token"] == "tok-B"
        assert saved_creds["subscription_key"] == "acc-B"

    def test_updates_build_dir_auth_json_when_provided(self, writer, work_dir, tmp_path):
        import json
        from unittest.mock import MagicMock, patch

        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        refreshed = {"tokens": {"refresh_token": "tok-B", "access_token": "acc-B"}}
        (codex_dir / "auth.json").write_text(json.dumps(refreshed))

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        token = self._make_token(refresh_token="tok-A")

        with patch("agento.modules.codex.src.config.register_token"):
            writer.capture_refreshed_credentials(work_dir, token, MagicMock(), build_dir)

        build_auth = build_dir / ".codex" / "auth.json"
        assert build_auth.is_file()
        assert json.loads(build_auth.read_text()) == refreshed

    def test_skips_build_dir_update_when_build_dir_is_none(self, writer, work_dir):
        import json
        from unittest.mock import MagicMock, patch

        codex_dir = work_dir / ".codex"
        codex_dir.mkdir(parents=True)
        refreshed = {"tokens": {"refresh_token": "tok-B", "access_token": "acc-B"}}
        (codex_dir / "auth.json").write_text(json.dumps(refreshed))

        token = self._make_token(refresh_token="tok-A")

        with patch("agento.modules.codex.src.config.register_token"):
            writer.capture_refreshed_credentials(work_dir, token, MagicMock(), None)
        # No assertion needed — just verifies no AttributeError on None
