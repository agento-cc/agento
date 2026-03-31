from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PeriodicTasksConfig:
    jira_status: str = ""
    jira_frequency_field: str = ""
    frequency_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodicTasksConfig:
        return cls(
            jira_status=data.get("jira_status", ""),
            jira_frequency_field=data.get("jira_frequency_field", ""),
            frequency_map=data.get("frequency_map", {}),
        )
