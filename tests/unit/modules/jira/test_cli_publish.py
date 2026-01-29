"""Tests for PublishCommand — especially that updated is threaded from task list to publish_todo."""
from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from agento.framework.database_config import DatabaseConfig
from agento.modules.jira.src.config import JiraConfig
from agento.modules.jira.src.models import JiraIssue, TaskAction, TaskPriority, TaskSource


def _make_args(kind: str, issue_key: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(kind=kind, issue_key=issue_key)


def _make_task(issue_key: str, updated: str | None) -> TaskAction:
    issue = JiraIssue(
        key=issue_key,
        summary="Test task",
        status="To Do",
        updated=updated,
    )
    return TaskAction(
        source=TaskSource.TODO_ASSIGNED,
        priority=TaskPriority.HIGH,
        issue=issue,
        reason="assigned",
    )


def _mock_configs():
    """Return (DatabaseConfig, JiraConfig) tuple for publish command tests."""
    db = DatabaseConfig()
    jira = JiraConfig(
        toolbox_url="http://toolbox:3001",
        user="ai@example.com",
        jira_assignee="ai@example.com",
    )
    return db, jira


class TestCmdPublishTodoDispatch:
    """PublishCommand jira-todo (no issue_key) should pass updated from task to publish_todo."""

    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish._load_configs", return_value=_mock_configs())
    @patch("agento.modules.jira.src.commands.publish.publish_todo")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    def test_passes_updated_to_publish_todo(
        self, mock_logger, mock_publish_todo, mock_config_fn, mock_toolbox_cls, mock_builder_cls
    ):
        task = _make_task("AI-6", updated="2026-02-24T16:45:00.000+0000")
        builder = MagicMock()
        builder.get_todo_tasks.return_value = [task]
        mock_builder_cls.return_value = builder

        mock_publish_todo.return_value = True

        from agento.modules.jira.src.commands.publish import PublishCommand

        PublishCommand().execute(_make_args("jira-todo"))

        mock_publish_todo.assert_called_once()
        _, kwargs = mock_publish_todo.call_args
        assert kwargs.get("updated") == "2026-02-24T16:45:00.000+0000"

    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish._load_configs", return_value=_mock_configs())
    @patch("agento.modules.jira.src.commands.publish.publish_todo")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    def test_passes_issue_key_to_publish_todo(
        self, mock_logger, mock_publish_todo, mock_config_fn, mock_toolbox_cls, mock_builder_cls
    ):
        task = _make_task("AI-6", updated="2026-02-24T16:45:00.000+0000")
        builder = MagicMock()
        builder.get_todo_tasks.return_value = [task]
        mock_builder_cls.return_value = builder

        mock_publish_todo.return_value = True

        from agento.modules.jira.src.commands.publish import PublishCommand

        PublishCommand().execute(_make_args("jira-todo"))

        _, kwargs = mock_publish_todo.call_args
        assert kwargs.get("issue_key") == "AI-6"

    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish._load_configs", return_value=_mock_configs())
    @patch("agento.modules.jira.src.commands.publish.publish_todo")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    def test_no_tasks_skips_publish(
        self, mock_logger, mock_publish_todo, mock_config_fn, mock_toolbox_cls, mock_builder_cls
    ):
        builder = MagicMock()
        builder.get_todo_tasks.return_value = []
        mock_builder_cls.return_value = builder

        from agento.modules.jira.src.commands.publish import PublishCommand

        PublishCommand().execute(_make_args("jira-todo"))

        mock_publish_todo.assert_not_called()
