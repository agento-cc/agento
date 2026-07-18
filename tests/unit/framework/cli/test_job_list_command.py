from __future__ import annotations

import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _args(status=None, source=None, agent_view=None, limit=20) -> argparse.Namespace:
    return argparse.Namespace(status=status, source=source, agent_view=agent_view, limit=limit)


class TestJobListCommand:
    def test_name_and_shortcut(self):
        from agento.framework.cli.runtime import JobListCommand

        cmd = JobListCommand()
        assert cmd.name == "job:list"
        assert cmd.shortcut == "jo:li"

    @patch("agento.framework.admin.data.get_jobs")
    @patch("agento.framework.cli.runtime.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_renders_rows_and_error_line_for_dead(self, mock_config, mock_conn, mock_get_jobs, capsys):
        from agento.framework.cli.runtime import JobListCommand

        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_get_jobs.return_value = [
            {
                "id": 7, "type": "CRON", "status": "DEAD", "source": "outlook",
                "reference_id": "outlook:mail:abc", "agent_type": "claude",
                "created_at": datetime(2026, 7, 4, 9, 30),
                "error_class": "ValueError", "error_message": "boom happened",
                "agent_view_code": "developer",
            },
            {
                "id": 6, "type": "CRON", "status": "SUCCESS", "source": "jira",
                "reference_id": "AI-1", "agent_type": "codex",
                "created_at": datetime(2026, 7, 4, 9, 0),
                "error_class": None, "error_message": None, "agent_view_code": "developer",
            },
        ]

        JobListCommand().execute(_args(status="DEAD", source="outlook"))
        out = capsys.readouterr().out
        assert "7" in out and "DEAD" in out and "outlook" in out
        # Failed/dead rows get an error line; success rows do not.
        assert "ValueError" in out and "boom happened" in out
        conn.close.assert_called_once()

    @patch("agento.framework.admin.data.get_jobs")
    @patch("agento.framework.cli.runtime.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_empty_prints_no_jobs(self, mock_config, mock_conn, mock_get_jobs, capsys):
        from agento.framework.cli.runtime import JobListCommand

        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_conn.return_value = MagicMock()
        mock_get_jobs.return_value = []

        JobListCommand().execute(_args())
        assert "No jobs found." in capsys.readouterr().out

    @patch("agento.framework.admin.data.get_jobs")
    @patch("agento.framework.cli.runtime.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_passes_filters_and_strict_true(self, mock_config, mock_conn, mock_get_jobs):
        from agento.framework.cli.runtime import JobListCommand

        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_conn.return_value = MagicMock()
        mock_get_jobs.return_value = []

        JobListCommand().execute(_args(status="FAILED", source="jira", agent_view="dev", limit=5))
        _, kwargs = mock_get_jobs.call_args
        assert kwargs["status"] == "FAILED"
        assert kwargs["source"] == "jira"
        assert kwargs["agent_view_code"] == "dev"
        assert kwargs["limit"] == 5
        assert kwargs["strict"] is True

    @patch("agento.framework.admin.data.get_jobs")
    @patch("agento.framework.cli.runtime.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_query_error_exits_nonzero(self, mock_config, mock_conn, mock_get_jobs, capsys):
        from agento.framework.cli.runtime import JobListCommand

        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_get_jobs.side_effect = RuntimeError("db down")

        with pytest.raises(SystemExit) as exc:
            JobListCommand().execute(_args())
        assert exc.value.code == 1
        assert "could not query jobs" in capsys.readouterr().err
        conn.close.assert_called_once()
