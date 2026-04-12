"""Jira module configuration dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JiraConfig:
    """Typed configuration for the Jira module.

    Replaces the Jira-specific fields that were in CronConfig.
    Constructed from the resolved module config dict via ``from_dict()``.
    """

    enabled: bool = True
    toolbox_url: str = ""
    user: str = ""
    jira_projects: list[str] = field(default_factory=list)
    jira_assignee: str = ""
    jira_assignee_account_id: str = ""
    todo_statuses: list[str] = field(default_factory=lambda: ["To Do"])

    @property
    def jira_project_jql(self) -> str:
        """Return JQL fragment: 'project = X' or 'project IN (X, Y)'."""
        if len(self.jira_projects) == 1:
            return f"project = {self.jira_projects[0]}"
        return f"project IN ({', '.join(self.jira_projects)})"

    @property
    def todo_status_jql(self) -> str:
        """Return JQL fragment: 'status = "X"' or 'status IN ("X", "Y")'."""
        statuses = self.todo_statuses or ["To Do"]
        if len(statuses) == 1:
            return f'status = "{statuses[0]}"'
        quoted = ", ".join(f'"{s}"' for s in statuses)
        return f"status IN ({quoted})"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JiraConfig:
        """Build from a resolved config dict (3-level fallback output)."""
        projects = data.get("jira_projects", [])
        if isinstance(projects, str):
            projects = [p.strip() for p in projects.split(",")]
        todo_statuses = data.get("todo_statuses", ["To Do"])
        if isinstance(todo_statuses, str):
            import json as _json
            try:
                todo_statuses = _json.loads(todo_statuses)
            except (ValueError, TypeError):
                todo_statuses = [s.strip() for s in todo_statuses.split(",")]
        enabled_raw = data.get("enabled", True)
        enabled = enabled_raw not in (False, 0, "0", "false", "False")
        return cls(
            enabled=enabled,
            toolbox_url=data.get("toolbox_url", ""),
            user=data.get("user", ""),
            jira_projects=projects,
            jira_assignee=data.get("jira_assignee", ""),
            jira_assignee_account_id=data.get("jira_assignee_account_id", ""),
            todo_statuses=todo_statuses,
        )
