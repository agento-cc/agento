from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.job_models import AgentType
from agento.framework.publisher import publish


def _mock_connection(rowcount=1):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = rowcount
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


@patch("agento.framework.publisher.get_connection")
def test_publish_inserts_job(mock_get_conn, sample_config):
    mock_conn, mock_cursor = _mock_connection(rowcount=1)
    mock_get_conn.return_value = mock_conn

    result = publish(sample_config, AgentType.CRON, "jira", "key:1", reference_id="AI-1")

    assert result is True
    mock_cursor.execute.assert_called_once()
    sql_arg = mock_cursor.execute.call_args[0][0]
    assert "INSERT IGNORE" in sql_arg


@patch("agento.framework.publisher.get_connection")
def test_publish_duplicate_returns_false(mock_get_conn, sample_config):
    mock_conn, _mock_cursor = _mock_connection(rowcount=0)
    mock_get_conn.return_value = mock_conn

    result = publish(sample_config, AgentType.CRON, "jira", "key:dup")

    assert result is False


@patch("agento.framework.publisher.get_connection")
def test_publish_commits_on_success(mock_get_conn, sample_config):
    mock_conn, _mock_cursor = _mock_connection(rowcount=1)
    mock_get_conn.return_value = mock_conn

    publish(sample_config, AgentType.CRON, "jira", "key:commit")

    mock_conn.commit.assert_called_once()


@patch("agento.framework.publisher.get_connection")
def test_publish_rollback_on_error(mock_get_conn, sample_config):
    mock_conn, mock_cursor = _mock_connection()
    mock_cursor.execute.side_effect = RuntimeError("DB down")
    mock_get_conn.return_value = mock_conn

    with pytest.raises(RuntimeError, match="DB down"):
        publish(sample_config, AgentType.CRON, "jira", "key:fail")

    mock_conn.rollback.assert_called_once()


@patch("agento.framework.publisher.get_connection")
def test_publish_closes_connection(mock_get_conn, sample_config):
    mock_conn, mock_cursor = _mock_connection(rowcount=1)
    mock_get_conn.return_value = mock_conn

    publish(sample_config, AgentType.CRON, "jira", "key:close")
    mock_conn.close.assert_called_once()

    # Also verify close on failure path
    mock_conn.reset_mock()
    mock_cursor.execute.side_effect = RuntimeError("fail")
    mock_get_conn.return_value = mock_conn

    with pytest.raises(RuntimeError):
        publish(sample_config, AgentType.CRON, "jira", "key:close2")

    mock_conn.close.assert_called_once()
