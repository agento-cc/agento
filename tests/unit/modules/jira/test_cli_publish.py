"""Tests for PublishCommand — per-agent-view publishing and global fallback."""
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


def _make_jira_config(**kwargs):
    defaults = {
        "enabled": True,
        "toolbox_url": "http://toolbox:3001",
        "user": "ai@example.com",
        "jira_assignee": "ai@example.com",
    }
    defaults.update(kwargs)
    return JiraConfig(**defaults)


def _make_agent_view(id=1, workspace_id=1, code="dev"):
    av = MagicMock()
    av.id = id
    av.workspace_id = workspace_id
    av.code = code
    return av


class TestCmdPublishTodoDispatch:
    """PublishCommand jira-todo (no issue_key) — per-agent-view publishing."""

    @patch("agento.modules.jira.src.commands.publish._publisher")
    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    @patch("agento.modules.jira.src.commands.publish._get_connection_and_bootstrap")
    @patch("agento.framework.workspace.get_active_agent_views")
    @patch("agento.framework.scoped_config.get_module_config")
    @patch("agento.framework.agent_view_runtime.resolve_publish_priority", return_value=50)
    def test_passes_updated_to_publish_todo(
        self, mock_priority, mock_scoped_config, mock_get_avs,
        mock_bootstrap, mock_logger, mock_toolbox_cls, mock_builder_cls, mock_publisher,
    ):
        conn = MagicMock()
        mock_bootstrap.return_value = (DatabaseConfig(), conn)
        av = _make_agent_view()
        mock_get_avs.return_value = [av]
        mock_scoped_config.return_value = _make_jira_config()

        task = _make_task("AI-6", updated="2026-02-24T16:45:00.000+0000")
        builder = MagicMock()
        builder.get_todo_tasks.return_value = [task]
        mock_builder_cls.return_value = builder

        from agento.modules.jira.src.commands.publish import PublishCommand
        PublishCommand().execute(_make_args("jira-todo"))

        mock_publisher.publish_todo.assert_called_once()
        _, kwargs = mock_publisher.publish_todo.call_args
        assert kwargs.get("updated") == "2026-02-24T16:45:00.000+0000"
        assert kwargs.get("agent_view_id") == 1

    @patch("agento.modules.jira.src.commands.publish._publisher")
    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    @patch("agento.modules.jira.src.commands.publish._get_connection_and_bootstrap")
    @patch("agento.framework.workspace.get_active_agent_views")
    @patch("agento.framework.scoped_config.get_module_config")
    @patch("agento.framework.agent_view_runtime.resolve_publish_priority", return_value=50)
    def test_passes_issue_key_to_publish_todo(
        self, mock_priority, mock_scoped_config, mock_get_avs,
        mock_bootstrap, mock_logger, mock_toolbox_cls, mock_builder_cls, mock_publisher,
    ):
        conn = MagicMock()
        mock_bootstrap.return_value = (DatabaseConfig(), conn)
        av = _make_agent_view()
        mock_get_avs.return_value = [av]
        mock_scoped_config.return_value = _make_jira_config()

        task = _make_task("AI-6", updated="2026-02-24T16:45:00.000+0000")
        builder = MagicMock()
        builder.get_todo_tasks.return_value = [task]
        mock_builder_cls.return_value = builder

        from agento.modules.jira.src.commands.publish import PublishCommand
        PublishCommand().execute(_make_args("jira-todo"))

        _, kwargs = mock_publisher.publish_todo.call_args
        assert kwargs.get("issue_key") == "AI-6"

    @patch("agento.modules.jira.src.commands.publish._publisher")
    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    @patch("agento.modules.jira.src.commands.publish._get_connection_and_bootstrap")
    @patch("agento.framework.workspace.get_active_agent_views")
    @patch("agento.framework.scoped_config.get_module_config")
    @patch("agento.framework.agent_view_runtime.resolve_publish_priority", return_value=50)
    def test_no_tasks_skips_publish(
        self, mock_priority, mock_scoped_config, mock_get_avs,
        mock_bootstrap, mock_logger, mock_toolbox_cls, mock_builder_cls, mock_publisher,
    ):
        conn = MagicMock()
        mock_bootstrap.return_value = (DatabaseConfig(), conn)
        av = _make_agent_view()
        mock_get_avs.return_value = [av]
        mock_scoped_config.return_value = _make_jira_config()

        builder = MagicMock()
        builder.get_todo_tasks.return_value = []
        mock_builder_cls.return_value = builder

        from agento.modules.jira.src.commands.publish import PublishCommand
        PublishCommand().execute(_make_args("jira-todo"))

        mock_publisher.publish_todo.assert_not_called()

    @patch("agento.modules.jira.src.commands.publish._publisher")
    @patch("agento.modules.jira.src.commands.publish.TaskListBuilder")
    @patch("agento.modules.jira.src.commands.publish.ToolboxClient")
    @patch("agento.modules.jira.src.commands.publish.get_logger")
    @patch("agento.modules.jira.src.commands.publish._get_connection_and_bootstrap")
    @patch("agento.framework.workspace.get_active_agent_views")
    @patch("agento.framework.scoped_config.get_module_config")
    @patch("agento.framework.agent_view_runtime.resolve_publish_priority", return_value=50)
    def test_skips_disabled_agent_view(
        self, mock_priority, mock_scoped_config, mock_get_avs,
        mock_bootstrap, mock_logger, mock_toolbox_cls, mock_builder_cls, mock_publisher,
    ):
        conn = MagicMock()
        mock_bootstrap.return_value = (DatabaseConfig(), conn)
        mock_get_avs.return_value = [_make_agent_view()]
        mock_scoped_config.return_value = _make_jira_config(enabled=False)

        from agento.modules.jira.src.commands.publish import PublishCommand
        PublishCommand().execute(_make_args("jira-todo"))

        mock_publisher.publish_todo.assert_not_called()
