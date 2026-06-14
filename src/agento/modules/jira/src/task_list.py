from __future__ import annotations

import logging
from urllib.parse import quote

from .models import JiraIssue, TaskAction, TaskPriority, TaskSource
from .toolbox_client import ToolboxClient


class TaskListBuilder:
    """Build a prioritized list of actionable tasks from Jira.

    Simulates what a human Jira user would react to.
    """

    TERMINAL_STATUSES = ("Done", "Closed", "Resolved", "Cykliczne")
    _CHANGELOG_PAGE = 100
    _CHANGELOG_MAX_PAGES = 20            # safety bound; 2000 entries

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
            reporter_email=reporter.get("emailAddress"),
            priority=(f.get("priority") or {}).get("name"),
            created=f.get("created"),
            updated=f.get("updated"),
        )

    def get_status_change(self, issue_key: str, status: str) -> tuple[dict | None, bool]:
        """(changelog entry of the most recent transition INTO `status`, scan_complete).

        scan_complete is False when the changelog could not be fully read (fetch error
        or page cap). An incomplete scan must NOT yield a status_change actor: a later
        unfetched page (oldest-to-newest order) could hold a newer transition, so a
        partial match is not authoritative. The caller uses scan_complete to record an
        honest fallback_reason on the reporter fallback.
        """
        matched = None
        start_at = 0
        key = quote(issue_key, safe="")                  # encode as path segment (proxy forwards path verbatim)
        for _page in range(self._CHANGELOG_MAX_PAGES):
            try:
                data = self.toolbox.jira_request(
                    "GET",
                    f"/rest/api/3/issue/{key}/changelog"
                    f"?startAt={start_at}&maxResults={self._CHANGELOG_PAGE}",
                    agent_view_id=self.agent_view_id,
                )
            except Exception:
                self.logger.exception("changelog fetch failed for %s; using reporter fallback", issue_key)
                return None, False                       # incomplete -> reporter fallback
            values = data.get("values", [])              # oldest-to-newest
            for entry in values:
                for item in entry.get("items", []):
                    if item.get("field") == "status" and item.get("toString") == status:
                        matched = entry                  # keep latest match
            next_at = data.get("startAt", start_at) + len(values)
            total = data.get("total")
            is_last = data.get("isLast")
            if is_last is None:                          # defensive: Atlassian normally returns isLast
                is_last = (not values) or (total is not None and next_at >= total)
            if is_last:
                return matched, True                     # authoritative: full scan completed
            start_at = next_at
        self.logger.warning("changelog pagination capped (%d pages) for %s; using reporter fallback",
                            self._CHANGELOG_MAX_PAGES, issue_key)
        return None, False                               # cap hit -> incomplete -> reporter fallback
