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

    toolbox_url: str = ""
    user: str = ""
    jira_projects: list[str] = field(default_factory=list)
    jira_assignee: str = ""
    jira_assignee_account_id: str = ""

    @property
    def jira_project_jql(self) -> str:
        """Return JQL fragment: 'project = X' or 'project IN (X, Y)'."""
        if len(self.jira_projects) == 1:
            return f"project = {self.jira_projects[0]}"
        return f"project IN ({', '.join(self.jira_projects)})"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JiraConfig:
        """Build from a resolved config dict (3-level fallback output)."""
        projects = data.get("jira_projects", [])
        if isinstance(projects, str):
            projects = [p.strip() for p in projects.split(",")]
        return cls(
            toolbox_url=data.get("toolbox_url", ""),
            user=data.get("user", ""),
            jira_projects=projects,
            jira_assignee=data.get("jira_assignee", ""),
            jira_assignee_account_id=data.get("jira_assignee_account_id", ""),
        )
