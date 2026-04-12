"""Tests for jira module onboarding flow."""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from agento.modules.jira.src.onboarding import JiraOnboarding, _parse_jira_url
from agento.modules.jira.src.toolbox_client import ToolboxAPIError


def _mock_conn(db_overrides=None):
    """Create a mock DB connection with configurable core_config_data rows."""
    conn = MagicMock()
    cursor = MagicMock()

    rows = []
    if db_overrides:
        for path, value in db_overrides.items():
            rows.append({"path": path, "value": value, "encrypted": 0})

    cursor.fetchall.return_value = rows
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


_ALL_KEYS = {
    "jira/jira_token": "tok",
    "jira/jira_host": "https://myteam.atlassian.net",
    "jira/jira_user": "user@example.com",
    "jira/jira_projects": '["AI"]',
}


class TestIsComplete:
    def test_complete_when_all_keys_exist(self):
        conn = _mock_conn(_ALL_KEYS)
        assert JiraOnboarding().is_complete(conn) is True

    @pytest.mark.parametrize("missing_key", list(_ALL_KEYS.keys()))
    def test_incomplete_when_key_missing(self, missing_key):
        overrides = {k: v for k, v in _ALL_KEYS.items() if k != missing_key}
        conn = _mock_conn(overrides)
        assert JiraOnboarding().is_complete(conn) is False

    @pytest.mark.parametrize("empty_key", list(_ALL_KEYS.keys()))
    def test_incomplete_when_key_empty(self, empty_key):
        overrides = {**_ALL_KEYS, empty_key: ""}
        conn = _mock_conn(overrides)
        assert JiraOnboarding().is_complete(conn) is False

    def test_incomplete_when_all_missing(self):
        conn = _mock_conn({})
        assert JiraOnboarding().is_complete(conn) is False


class TestDescribe:
    def test_returns_description(self):
        desc = JiraOnboarding().describe()
        assert "Jira connection" in desc
        assert "project keys" in desc


class TestParseJiraUrl:
    def test_issue_url(self):
        host, key = _parse_jira_url("https://myteam.atlassian.net/browse/AI-123")
        assert host == "https://myteam.atlassian.net"
        assert key == "AI"

    def test_project_board_url(self):
        host, key = _parse_jira_url("https://myteam.atlassian.net/jira/software/projects/AI/board")
        assert host == "https://myteam.atlassian.net"
        assert key == "AI"

    def test_bare_host(self):
        host, key = _parse_jira_url("https://myteam.atlassian.net")
        assert host == "https://myteam.atlassian.net"
        assert key is None

    def test_host_with_trailing_slash(self):
        host, key = _parse_jira_url("https://myteam.atlassian.net/")
        assert host == "https://myteam.atlassian.net"
        assert key is None

    def test_issue_url_with_multi_digit(self):
        host, key = _parse_jira_url("https://corp.atlassian.net/browse/PROJ-9999")
        assert host == "https://corp.atlassian.net"
        assert key == "PROJ"

    def test_no_scheme(self):
        host, key = _parse_jira_url("myteam.atlassian.net")
        assert host == "myteam.atlassian.net"
        assert key is None


def _make_toolbox_mock(responses=None):
    """Create a ToolboxClient mock with configurable jira_request responses."""
    toolbox = MagicMock()
    default_responses = {
        ("GET", "/rest/api/3/serverInfo"): {"baseUrl": "https://myteam.atlassian.net"},
        ("GET", "/rest/api/3/myself"): {
            "accountId": "abc123",
            "displayName": "Agent Bot",
            "emailAddress": "agent@example.com",
        },
        ("GET", "/rest/api/3/project/AI"): {"id": "10001", "key": "AI"},
    }
    if responses:
        default_responses.update(responses)

    def jira_request_side_effect(method, path, body=None):
        key = (method, path)
        for k, v in default_responses.items():
            if k == key:
                if isinstance(v, Exception):
                    raise v
                return v
        return {}

    toolbox.jira_request.side_effect = jira_request_side_effect
    return toolbox


class TestRun:
    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_happy_path(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = _make_toolbox_mock()
        mock_toolbox_cls.return_value = toolbox

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",  # URL
            "agent@example.com",                            # email
            "my-api-token",                                 # token
            "",                                             # additional projects (skip)
            "",                                             # admin token (skip)
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        # Token saved via auto_encrypt
        mock_auto_encrypt.assert_called_once_with(conn, "jira/jira_token", "my-api-token")

        # Other config saved via config_set
        set_calls = {c.args[1]: c.args[2] for c in mock_config_set.call_args_list}
        assert set_calls["jira/jira_host"] == "https://myteam.atlassian.net"
        assert set_calls["jira/jira_user"] == "agent@example.com"
        assert set_calls["jira/jira_assignee"] == "Agent Bot"
        assert set_calls["jira/jira_assignee_account_id"] == "abc123"
        assert json.loads(set_calls["jira/jira_projects"]) == ["AI"]

        assert conn.commit.call_count == 2  # early commit (credentials) + final commit

    @patch("agento.modules.jira.src.onboarding.get_module_config")
    def test_aborts_when_toolbox_url_missing(self, mock_get_config, capsys):
        mock_get_config.return_value = {}

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        output = capsys.readouterr().out
        assert "toolbox_url not configured" in output

    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_aborts_on_toolbox_unreachable(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch, capsys):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = MagicMock()
        mock_toolbox_cls.return_value = toolbox
        toolbox.jira_request.side_effect = Exception("Connection refused")

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",
            "user@example.com",
            "my-token",
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        output = capsys.readouterr().out
        assert "Toolbox not reachable" in output

    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_aborts_on_jira_auth_failure(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch, capsys):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = _make_toolbox_mock({
            ("GET", "/rest/api/3/myself"): ToolboxAPIError(401, "Unauthorized"),
        })
        mock_toolbox_cls.return_value = toolbox

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",
            "user@example.com",
            "bad-token",
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        output = capsys.readouterr().out
        assert "authentication failed" in output

    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_aborts_on_project_validation_failure(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch, capsys):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = _make_toolbox_mock({
            ("GET", "/rest/api/3/project/AI"): ToolboxAPIError(404, "Not found"),
        })
        mock_toolbox_cls.return_value = toolbox

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",
            "user@example.com",
            "my-token",
            "",  # no additional projects
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        output = capsys.readouterr().out
        assert "not accessible" in output
        assert "At least one valid project key is required" in output
        conn.commit.assert_called_once()  # early commit for credentials only

    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_additional_projects(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = _make_toolbox_mock({
            ("GET", "/rest/api/3/project/AI"): {"id": "10001"},
            ("GET", "/rest/api/3/project/WEB"): {"id": "10002"},
            ("GET", "/rest/api/3/project/API"): {"id": "10003"},
        })
        mock_toolbox_cls.return_value = toolbox

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",
            "agent@example.com",
            "my-token",
            " WEB , API ",  # additional with whitespace
            "",             # admin token (skip)
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        set_calls = {c.args[1]: c.args[2] for c in mock_config_set.call_args_list}
        assert json.loads(set_calls["jira/jira_projects"]) == ["AI", "WEB", "API"]
        assert conn.commit.call_count == 2

    @patch("agento.modules.jira.src.onboarding.ToolboxClient")
    @patch("agento.modules.jira.src.onboarding.get_module_config")
    @patch("agento.modules.jira.src.onboarding.config_set")
    @patch("agento.modules.jira.src.onboarding.config_set_auto_encrypt")
    def test_no_duplicate_projects(self, mock_auto_encrypt, mock_config_set, mock_get_config, mock_toolbox_cls, monkeypatch):
        mock_get_config.return_value = {"toolbox_url": "http://toolbox:3001"}
        toolbox = _make_toolbox_mock({
            ("GET", "/rest/api/3/project/AI"): {"id": "10001"},
        })
        mock_toolbox_cls.return_value = toolbox

        inputs = iter([
            "https://myteam.atlassian.net/browse/AI-123",
            "agent@example.com",
            "my-token",
            "AI",   # duplicate of auto-detected
            "",     # admin token (skip)
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        conn = _mock_conn({})
        JiraOnboarding().run(conn, {}, logging.getLogger("test"))

        set_calls = {c.args[1]: c.args[2] for c in mock_config_set.call_args_list}
        assert json.loads(set_calls["jira/jira_projects"]) == ["AI"]
