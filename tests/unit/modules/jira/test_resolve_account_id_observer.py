"""Tests for ResolveAccountIdObserver."""
from unittest.mock import MagicMock, call, patch

from agento.modules.jira.src.config import JiraConfig
from agento.modules.jira.src.observers import ResolveAccountIdObserver


def _make_event(name="jira"):
    event = MagicMock()
    event.name = name
    return event


def _make_config(**overrides):
    defaults = {
        "toolbox_url": "http://toolbox:3001",
        "user": "agent@test.com",
        "jira_projects": ["TEST"],
        "jira_assignee": "Agent",
        "jira_assignee_account_id": "",
    }
    defaults.update(overrides)
    return JiraConfig(**defaults)


def _make_agent_view(id=1, workspace_id=10, code="dev_01"):
    av = MagicMock()
    av.id = id
    av.workspace_id = workspace_id
    av.code = code
    av.is_active = True
    return av


_FWK = "agento.framework"
_OBS = "agento.modules.jira.src.observers"


class TestSkipConditions:
    def test_skips_non_jira_module(self):
        observer = ResolveAccountIdObserver()
        observer.execute(_make_event(name="other"))

    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_skips_when_account_id_already_set(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            jira_assignee_account_id="712020:abc"
        )
        observer = ResolveAccountIdObserver()
        # Patch out agent_view resolution to isolate the skip check
        with patch.object(observer, "_resolve_agent_views"):
            observer.execute(_make_event())

    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_skips_when_no_toolbox_url(self, mock_get_config):
        mock_get_config.return_value = _make_config(toolbox_url="")
        observer = ResolveAccountIdObserver()
        observer.execute(_make_event())


class TestDefaultScopeResolve:
    @patch(f"{_FWK}.bootstrap.set_module_config")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    @patch(f"{_FWK}.db.get_connection")
    @patch(f"{_FWK}.database_config.DatabaseConfig.from_env")
    @patch(f"{_FWK}.core_config.config_set")
    @patch(f"{_OBS}._resolve_account_id", return_value="712020:abc-123")
    def test_resolves_and_saves_account_id(
        self, mock_resolve, mock_config_set, mock_db_config,
        mock_get_conn, mock_get_config, mock_set_config,
    ):
        mock_get_config.return_value = _make_config()
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        observer = ResolveAccountIdObserver()
        with patch.object(observer, "_resolve_agent_views"):
            observer.execute(_make_event())

        mock_resolve.assert_called_once_with("http://toolbox:3001")
        mock_config_set.assert_called_once_with(
            mock_conn, "jira/jira_assignee_account_id", "712020:abc-123"
        )
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

        updated_config = mock_set_config.call_args[0][1]
        assert updated_config.jira_assignee_account_id == "712020:abc-123"

    @patch(f"{_FWK}.bootstrap.set_module_config")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    @patch(f"{_OBS}._resolve_account_id", return_value=None)
    def test_skips_when_myself_missing_account_id(
        self, mock_resolve, mock_get_config, mock_set_config,
    ):
        mock_get_config.return_value = _make_config()

        observer = ResolveAccountIdObserver()
        with patch.object(observer, "_resolve_agent_views"):
            observer.execute(_make_event())

        mock_set_config.assert_not_called()


class TestAgentViewScopeResolve:
    @patch(f"{_FWK}.workspace.get_active_agent_views")
    @patch(f"{_FWK}.db.get_connection")
    @patch(f"{_FWK}.database_config.DatabaseConfig.from_env")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_resolves_for_agent_view_with_credentials(
        self, mock_get_config, mock_db_config, mock_get_conn, mock_get_avs,
    ):
        mock_get_config.return_value = _make_config(
            jira_assignee_account_id="already-set"
        )
        av = _make_agent_view(id=2, code="dev_01")
        mock_get_avs.return_value = [av]
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        sc_values = {
            "jira/jira_assignee_account_id": None,  # empty
            "jira/jira_user": "user@dev.com",
            "jira/jira_token": "tok-123",
            "jira/jira_host": "https://dev.atlassian.net",
        }

        with patch(f"{_FWK}.scoped_config.ScopedConfig") as mock_sc_cls, \
             patch(f"{_FWK}.scoped_config.scoped_config_set") as mock_scoped_set, \
             patch(f"{_OBS}._resolve_account_id", return_value="712020:dev-abc") as mock_resolve:
            mock_sc = MagicMock()
            mock_sc.get_value.side_effect = lambda path: sc_values.get(path)
            mock_sc_cls.return_value = mock_sc

            observer = ResolveAccountIdObserver()
            observer.execute(_make_event())

        mock_resolve.assert_called_once_with(
            "http://toolbox:3001", auth_user="user@dev.com", auth_token="tok-123",
            jira_host="https://dev.atlassian.net",
        )
        mock_scoped_set.assert_called_once_with(
            mock_conn, "jira/jira_assignee_account_id", "712020:dev-abc",
            scope="agent_view", scope_id=2,
        )

    @patch(f"{_FWK}.workspace.get_active_agent_views")
    @patch(f"{_FWK}.db.get_connection")
    @patch(f"{_FWK}.database_config.DatabaseConfig.from_env")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_skips_agent_view_without_credentials(
        self, mock_get_config, mock_db_config, mock_get_conn, mock_get_avs,
    ):
        mock_get_config.return_value = _make_config(
            jira_assignee_account_id="already-set"
        )
        av = _make_agent_view(id=3, code="no_creds")
        mock_get_avs.return_value = [av]
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        sc_values = {
            "jira/jira_assignee_account_id": None,
            "jira/jira_user": None,
            "jira/jira_token": None,
        }

        with patch(f"{_FWK}.scoped_config.ScopedConfig") as mock_sc_cls, \
             patch(f"{_OBS}._resolve_account_id") as mock_resolve:
            mock_sc = MagicMock()
            mock_sc.get_value.side_effect = lambda path: sc_values.get(path)
            mock_sc_cls.return_value = mock_sc

            observer = ResolveAccountIdObserver()
            observer.execute(_make_event())

        mock_resolve.assert_not_called()

    @patch(f"{_FWK}.workspace.get_active_agent_views")
    @patch(f"{_FWK}.db.get_connection")
    @patch(f"{_FWK}.database_config.DatabaseConfig.from_env")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_skips_agent_view_with_existing_account_id(
        self, mock_get_config, mock_db_config, mock_get_conn, mock_get_avs,
    ):
        mock_get_config.return_value = _make_config(
            jira_assignee_account_id="already-set"
        )
        av = _make_agent_view(id=2, code="dev_01")
        mock_get_avs.return_value = [av]
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        sc_values = {
            "jira/jira_assignee_account_id": "712020:exists",
            "jira/jira_user": "user@dev.com",
            "jira/jira_token": "tok",
        }

        with patch(f"{_FWK}.scoped_config.ScopedConfig") as mock_sc_cls, \
             patch(f"{_OBS}._resolve_account_id") as mock_resolve:
            mock_sc = MagicMock()
            mock_sc.get_value.side_effect = lambda path: sc_values.get(path)
            mock_sc_cls.return_value = mock_sc

            observer = ResolveAccountIdObserver()
            observer.execute(_make_event())

        mock_resolve.assert_not_called()


class TestErrorHandling:
    @patch(f"{_FWK}.bootstrap.get_module_config")
    @patch(f"{_OBS}._resolve_account_id", side_effect=ConnectionError("toolbox down"))
    def test_handles_toolbox_error_gracefully(self, mock_resolve, mock_get_config):
        mock_get_config.return_value = _make_config()

        observer = ResolveAccountIdObserver()
        observer.execute(_make_event())  # should not raise

    @patch(f"{_FWK}.workspace.get_active_agent_views", side_effect=RuntimeError("DB down"))
    @patch(f"{_FWK}.db.get_connection")
    @patch(f"{_FWK}.database_config.DatabaseConfig.from_env")
    @patch(f"{_FWK}.bootstrap.get_module_config")
    def test_handles_agent_view_db_error_gracefully(
        self, mock_get_config, mock_db_config, mock_get_conn, mock_get_avs,
    ):
        mock_get_config.return_value = _make_config(
            jira_assignee_account_id="already-set"
        )
        mock_get_conn.return_value = MagicMock()

        observer = ResolveAccountIdObserver()
        observer.execute(_make_event())  # should not raise
