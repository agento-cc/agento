from __future__ import annotations

import json
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
    credentials: dict | None
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
            credentials=_decrypt_credentials(row.get("credentials")),
            model=row.get("model"),
            is_primary=bool(row.get("is_primary", False)),
            token_limit=row["token_limit"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _decrypt_credentials(raw: str | None) -> dict | None:
    if not raw:
        return None
    from ..encryptor import get_encryptor
    plaintext = get_encryptor().decrypt(raw)
    return json.loads(plaintext)


def encrypt_credentials(credentials: dict) -> str:
    """Encrypt a plaintext credentials dict for storage in oauth_token.credentials."""
    from ..encryptor import get_encryptor
    return get_encryptor().encrypt(json.dumps(credentials))


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
