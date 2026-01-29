from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskPriority(Enum):
    HIGH = 2


class TaskSource(Enum):
    TODO_ASSIGNED = "todo_assigned"
    MENTION_UNANSWERED = "mention_unanswered"


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str | None = None
    status: str = ""
    assignee: str | None = None
    assignee_account_id: str | None = None
    reporter: str | None = None
    reporter_account_id: str | None = None
    priority: str | None = None
    created: str | None = None
    updated: str | None = None
    frequency_value: str | None = None


@dataclass
class TaskAction:
    source: TaskSource
    priority: TaskPriority
    issue: JiraIssue
    reason: str
    context: dict = field(default_factory=dict)
