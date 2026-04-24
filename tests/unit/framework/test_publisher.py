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


class TestSkipIfActive:
    """Guard: when skip_if_active=True and reference_id is set, block publish
    if a non-terminal job already exists for (type, source, agent_view_id,
    reference_id). Prevents duplicate enqueues from Jira index lag and
    similar races when the idempotency key rotates on every remote update.
    """

    @patch("agento.framework.publisher.get_connection")
    def test_blocks_when_active_job_exists(self, mock_get_conn, sample_config):
        mock_conn, mock_cursor = _mock_connection()
        mock_cursor.fetchone.return_value = (1,)
        mock_get_conn.return_value = mock_conn

        result = publish(
            sample_config, AgentType.TODO, "jira", "key:new",
            reference_id="AI-64", agent_view_id=2, skip_if_active=True,
        )

        assert result is False
        sql_calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert any("SELECT" in sql for sql in sql_calls)
        assert not any("INSERT" in sql for sql in sql_calls)

    @patch("agento.framework.publisher.get_connection")
    def test_inserts_when_no_active_job(self, mock_get_conn, sample_config):
        mock_conn, mock_cursor = _mock_connection(rowcount=1)
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        result = publish(
            sample_config, AgentType.TODO, "jira", "key:new",
            reference_id="AI-64", agent_view_id=2, skip_if_active=True,
        )

        assert result is True
        sql_calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert any("SELECT" in sql for sql in sql_calls)
        assert any("INSERT IGNORE" in sql for sql in sql_calls)

    @patch("agento.framework.publisher.get_connection")
    def test_no_precheck_without_reference_id(self, mock_get_conn, sample_config):
        mock_conn, mock_cursor = _mock_connection(rowcount=1)
        mock_get_conn.return_value = mock_conn

        result = publish(
            sample_config, AgentType.TODO, "jira", "key:x",
            reference_id=None, skip_if_active=True,
        )

        assert result is True
        sql_calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert not any("SELECT" in sql for sql in sql_calls)

    @patch("agento.framework.publisher.get_connection")
    def test_disabled_by_default(self, mock_get_conn, sample_config):
        mock_conn, mock_cursor = _mock_connection(rowcount=1)
        mock_get_conn.return_value = mock_conn

        publish(sample_config, AgentType.TODO, "jira", "key:d", reference_id="AI-1")

        sql_calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert not any("SELECT" in sql for sql in sql_calls)

    @patch("agento.framework.publisher.get_connection")
    def test_precheck_filters_by_type_source_view_and_reference(
        self, mock_get_conn, sample_config
    ):
        mock_conn, mock_cursor = _mock_connection(rowcount=1)
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        publish(
            sample_config, AgentType.TODO, "jira", "key:p",
            reference_id="AI-64", agent_view_id=2, skip_if_active=True,
        )

        select_call = next(
            c for c in mock_cursor.execute.call_args_list
            if "SELECT" in c[0][0]
        )
        sql, params = select_call[0][0], select_call[0][1]
        assert "type" in sql and "source" in sql
        assert "agent_view_id" in sql and "reference_id" in sql
        assert "status" in sql
        assert params == ("todo", "jira", 2, "AI-64")
