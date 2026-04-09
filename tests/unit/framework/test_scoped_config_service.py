"""Tests for ScopedConfig class — recursive scope fallback service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.scoped_config import ScopedConfig


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestEnvOverride:
    def test_env_wins_over_db_for_module_path(self, monkeypatch, mock_conn):
        monkeypatch.setenv("CONFIG__JIRA__TOKEN", "env-token")
        conn, cursor = mock_conn
        cursor.fetchone.return_value = {"value": "db-token", "encrypted": 0}

        sc = ScopedConfig(conn, scope="agent_view", scope_id=1)
        assert sc.get_value("jira/token") == "env-token"
        cursor.execute.assert_not_called()

    def test_tool_path_env_key_format(self, monkeypatch, mock_conn):
        monkeypatch.setenv("CONFIG__MYMOD__TOOLS__SEARCH__URL", "env-url")
        conn, cursor = mock_conn

        sc = ScopedConfig(conn)
        assert sc.get_value("mymod/tools/search/url") == "env-url"
        cursor.execute.assert_not_called()


class TestDbFallback:
    def test_agent_view_scope_returned_directly(self, mock_conn):
        conn, cursor = mock_conn
        cursor.fetchone.return_value = {"value": "av-val", "encrypted": 0}

        sc = ScopedConfig(conn, scope="agent_view", scope_id=5)
        assert sc.get_value("agent_view/model") == "av-val"
        # Should query with agent_view scope
        args = cursor.execute.call_args[0]
        assert args[1] == ("agent_view", 5, "agent_view/model")

    def test_fallback_agent_view_to_workspace(self):
        """When agent_view has no value, falls back to workspace."""
        call_count = [0]

        def make_cursor():
            cur = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                # agent_view query -> not found
                cur.fetchone.return_value = None
            elif idx == 1:
                # agent_view table lookup for workspace_id
                cur.fetchone.return_value = {"workspace_id": 3}
            else:
                # workspace query -> found
                cur.fetchone.return_value = {"value": "ws-val", "encrypted": 0}
            return cur

        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(side_effect=make_cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        sc = ScopedConfig(conn, scope="agent_view", scope_id=5)
        assert sc.get_value("agent_view/model") == "ws-val"

    def test_fallback_workspace_to_default(self):
        """When workspace has no value, falls back to default."""
        call_count = [0]

        def make_cursor():
            cur = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                # workspace query -> not found
                cur.fetchone.return_value = None
            else:
                # default query -> found
                cur.fetchone.return_value = {"value": "global-val", "encrypted": 0}
            return cur

        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(side_effect=make_cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        sc = ScopedConfig(conn, scope="workspace", scope_id=2)
        assert sc.get_value("agent_view/model") == "global-val"

    @patch("agento.framework.config_resolver.read_config_defaults", return_value={"token": "cfg-val"})
    @patch("agento.framework.bootstrap.get_manifests")
    def test_fallback_default_to_config_json(self, mock_manifests, mock_defaults, mock_conn):
        """When default DB has no value, falls back to config.json."""
        conn, cursor = mock_conn
        cursor.fetchone.return_value = None

        manifest = MagicMock()
        manifest.name = "jira"
        manifest.path = "/some/path"
        mock_manifests.return_value = [manifest]

        sc = ScopedConfig(conn, scope="default", scope_id=0)
        assert sc.get_value("jira/token") == "cfg-val"

    @patch("agento.framework.config_resolver.read_config_defaults", return_value={})
    @patch("agento.framework.bootstrap.get_manifests")
    def test_full_chain_returns_none(self, mock_manifests, mock_defaults):
        """When nothing found anywhere, returns None."""
        call_count = [0]

        def make_cursor():
            cur = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 1:
                # agent_view table -> workspace_id
                cur.fetchone.return_value = {"workspace_id": 2}
            else:
                cur.fetchone.return_value = None
            return cur

        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(side_effect=make_cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        manifest = MagicMock()
        manifest.name = "jira"
        manifest.path = "/some/path"
        mock_manifests.return_value = [manifest]

        sc = ScopedConfig(conn, scope="agent_view", scope_id=5)
        assert sc.get_value("jira/token") is None

    def test_default_scope_skips_to_db_default(self, mock_conn):
        """Default scope queries DB directly with scope=default, scope_id=0."""
        conn, cursor = mock_conn
        cursor.fetchone.return_value = {"value": "default-val", "encrypted": 0}

        sc = ScopedConfig(conn, scope="default", scope_id=0)
        assert sc.get_value("agent_view/model") == "default-val"
        args = cursor.execute.call_args[0]
        assert args[1] == ("default", 0, "agent_view/model")


class TestWorkspaceIdCaching:
    def test_workspace_id_cached_across_calls(self):
        """Second get_value call reuses cached workspace_id."""
        call_count = [0]

        def make_cursor():
            cur = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                # First get_value: agent_view query -> not found
                cur.fetchone.return_value = None
            elif idx == 1:
                # First get_value: workspace_id lookup
                cur.fetchone.return_value = {"workspace_id": 3}
            elif idx == 2:
                # First get_value: workspace query -> found
                cur.fetchone.return_value = {"value": "ws-val-1", "encrypted": 0}
            elif idx == 3:
                # Second get_value: agent_view query -> not found
                cur.fetchone.return_value = None
            else:
                # Second get_value: workspace query (no workspace_id lookup!)
                cur.fetchone.return_value = {"value": "ws-val-2", "encrypted": 0}
            return cur

        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(side_effect=make_cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        sc = ScopedConfig(conn, scope="agent_view", scope_id=5)
        sc.get_value("agent_view/model")
        sc.get_value("agent_view/provider")

        # 5 cursor calls total (not 6), proving workspace_id was cached
        assert call_count[0] == 5


class TestEncryption:
    def test_encrypted_value_is_decrypted(self, monkeypatch):
        monkeypatch.setenv("AGENTO_ENCRYPTION_KEY", "test-secret-key")
        from agento.framework.crypto import encrypt

        encrypted_val = encrypt("secret-token")

        cursor = MagicMock()
        cursor.fetchone.return_value = {"value": encrypted_val, "encrypted": 1}
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        sc = ScopedConfig(conn, scope="default", scope_id=0)
        assert sc.get_value("mymod/token") == "secret-token"


class TestConfigJsonFallback:
    @patch("agento.framework.config_resolver.read_config_defaults")
    @patch("agento.framework.bootstrap.get_manifests")
    def test_tool_path_config_json(self, mock_manifests, mock_defaults, mock_conn):
        """Tool path falls back to config.json tools section."""
        conn, cursor = mock_conn
        cursor.fetchone.return_value = None

        manifest = MagicMock()
        manifest.name = "mymod"
        manifest.path = "/some/path"
        mock_manifests.return_value = [manifest]
        mock_defaults.return_value = {"tools": {"search": {"url": "cfg-url"}}}

        sc = ScopedConfig(conn, scope="default", scope_id=0)
        assert sc.get_value("mymod/tools/search/url") == "cfg-url"

    @patch("agento.framework.bootstrap.get_manifests")
    def test_unknown_module_returns_none(self, mock_manifests, mock_conn):
        conn, cursor = mock_conn
        cursor.fetchone.return_value = None
        mock_manifests.return_value = []

        sc = ScopedConfig(conn, scope="default", scope_id=0)
        assert sc.get_value("unknown/field") is None
