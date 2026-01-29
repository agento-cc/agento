from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AgentProvider(Enum):
    CLAUDE = "claude"
    CODEX = "codex"


@dataclass
class Token:
    id: int
    agent_type: AgentProvider
    label: str
    credentials_path: str
    model: str | None
    is_primary: bool
    token_limit: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> Token:
        return cls(
            id=row["id"],
            agent_type=AgentProvider(row["agent_type"]),
            label=row["label"],
            credentials_path=row["credentials_path"],
            model=row.get("model"),
            is_primary=bool(row.get("is_primary", False)),
            token_limit=row["token_limit"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class UsageSummary:
    token_id: int
    total_tokens: int
    call_count: int


@dataclass
class RotationResult:
    agent_type: AgentProvider
    previous_token_id: int | None
    new_token_id: int
    reason: str
    timestamp: datetime
