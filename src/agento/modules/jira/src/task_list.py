from __future__ import annotations

import logging

from .models import JiraIssue, TaskAction, TaskPriority, TaskSource
from .toolbox_client import ToolboxClient


class TaskListBuilder:
    """Build a prioritized list of actionable tasks from Jira.

    Simulates what a human Jira user would react to.
    """

    TERMINAL_STATUSES = ("Done", "Closed", "Resolved", "Cykliczne")

    def __init__(
        self,
        toolbox: ToolboxClient,
        config: object,
        ai_user: str,
        logger: logging.Logger,
        agent_view_id: int | None = None,
    ):
        self.toolbox = toolbox
        self.config = config
        self.ai_user = ai_user
        self.logger = logger
        self.agent_view_id = agent_view_id

    def get_todo_tasks(self) -> list[TaskAction]:
        jql = (
            f'{self.config.jira_project_jql} '
            f'AND assignee = "{self.ai_user}" '
            f'AND {self.config.todo_status_jql} '
            f'ORDER BY priority DESC, created ASC'
        )
        return self._search_and_map(
            jql=jql,
            source=TaskSource.TODO_ASSIGNED,
            priority=TaskPriority.HIGH,
            reason="Assigned to you in 'To Do' status",
        )

    def get_unanswered_mentions(self) -> list[TaskAction]:
        terminal = ", ".join(f'"{s}"' for s in self.TERMINAL_STATUSES)
        # Use comment ~ accountId instead of text ~ email.
        # Jira indexes the accountId string from [~accountid:xxx] mentions
        # in comment bodies, but does NOT index the email address.
        account_id = self.config.jira_assignee_account_id
        if not account_id:
            return []
        jql = (
            f'{self.config.jira_project_jql} '
            f'AND comment ~ "{account_id}" '
            f'AND status NOT IN ({terminal}) '
            f'ORDER BY updated DESC'
        )
        return self._search_and_map(
            jql=jql,
            source=TaskSource.MENTION_UNANSWERED,
            priority=TaskPriority.HIGH,
            reason="You were mentioned in a comment",
        )

    def _search_and_map(
        self,
        jql: str,
        source: TaskSource,
        priority: TaskPriority,
        reason: str,
    ) -> list[TaskAction]:
        response = self.toolbox.jira_search(
            jql=jql,
            fields=["key", "summary", "description", "status", "priority", "assignee", "reporter", "created", "updated"],
            max_results=50,
            agent_view_id=self.agent_view_id,
        )
        return [
            TaskAction(
                source=source,
                priority=priority,
                issue=self._parse_issue(raw),
                reason=reason,
            )
            for raw in response.get("issues", [])
        ]

    @staticmethod
    def _parse_issue(raw: dict) -> JiraIssue:
        f = raw.get("fields", {})
        assignee = f.get("assignee") or {}
        reporter = f.get("reporter") or {}
        return JiraIssue(
            key=raw["key"],
            summary=f.get("summary", ""),
            description=f.get("description"),
            status=(f.get("status") or {}).get("name", ""),
            assignee=assignee.get("displayName"),
            assignee_account_id=assignee.get("accountId"),
            reporter=reporter.get("displayName"),
            reporter_account_id=reporter.get("accountId"),
            priority=(f.get("priority") or {}).get("name"),
            created=f.get("created"),
            updated=f.get("updated"),
        )
