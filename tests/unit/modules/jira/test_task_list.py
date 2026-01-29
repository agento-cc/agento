from __future__ import annotations

import logging

import httpx
import respx

from agento.modules.jira.src.models import TaskPriority, TaskSource
from agento.modules.jira.src.task_list import TaskListBuilder
from agento.modules.jira.src.toolbox_client import ToolboxClient


def _make_builder(toolbox: ToolboxClient, sample_config) -> TaskListBuilder:
    return TaskListBuilder(
        toolbox=toolbox,
        config=sample_config,
        ai_user="agenty@example.com",
        logger=logging.getLogger("test-task-list"),
    )


@respx.mock
def test_get_todo_tasks(sample_config, jira_todo):
    respx.post("http://toolbox:3001/api/jira/search").mock(
        return_value=httpx.Response(200, json=jira_todo)
    )
    client = ToolboxClient("http://toolbox:3001")
    builder = _make_builder(client, sample_config)

    tasks = builder.get_todo_tasks()

    assert len(tasks) == 2
    assert tasks[0].source == TaskSource.TODO_ASSIGNED
    assert tasks[0].priority == TaskPriority.HIGH
    assert tasks[0].issue.key == "AI-10"
    assert tasks[0].issue.summary == "Zaktualizuj dokumentację API"
    assert tasks[1].issue.key == "AI-11"


@respx.mock
def test_get_todo_tasks_empty(sample_config, jira_empty):
    respx.post("http://toolbox:3001/api/jira/search").mock(
        return_value=httpx.Response(200, json=jira_empty)
    )
    client = ToolboxClient("http://toolbox:3001")
    builder = _make_builder(client, sample_config)

    tasks = builder.get_todo_tasks()
    assert tasks == []


def test_parse_issue():
    raw = {
        "key": "AI-99",
        "fields": {
            "summary": "Test issue",
            "status": {"name": "In Progress"},
            "priority": {"name": "Medium"},
            "assignee": {"displayName": "Bot", "accountId": "bot-1"},
            "reporter": {"displayName": "Human", "accountId": "human-1"},
            "created": "2026-01-01T00:00:00.000+0100",
            "updated": "2026-02-01T00:00:00.000+0100",
        },
    }
    issue = TaskListBuilder._parse_issue(raw)
    assert issue.key == "AI-99"
    assert issue.summary == "Test issue"
    assert issue.status == "In Progress"
    assert issue.assignee == "Bot"
    assert issue.assignee_account_id == "bot-1"
    assert issue.reporter == "Human"
    assert issue.reporter_account_id == "human-1"
    assert issue.priority == "Medium"


def test_parse_issue_null_fields():
    raw = {
        "key": "AI-100",
        "fields": {
            "summary": "Minimal",
            "status": None,
            "priority": None,
            "assignee": None,
            "reporter": None,
            "created": None,
            "updated": None,
        },
    }
    issue = TaskListBuilder._parse_issue(raw)
    assert issue.key == "AI-100"
    assert issue.status == ""
    assert issue.assignee is None
    assert issue.reporter is None
    assert issue.priority is None
