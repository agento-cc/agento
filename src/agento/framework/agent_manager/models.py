from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AgentProvider(Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class TokenStatus(Enum):
    OK = "ok"
    ERROR = "error"


@dataclass
class Token:
    id: int
    agent_type: AgentProvider
    type: str
    label: str
    credentials: dict | None
    token_limit: int
    enabled: bool
    status: TokenStatus
    priority: int
    error_msg: str | None
    expires_at: datetime | None
    used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> Token:
        return cls(
            id=row["id"],
            agent_type=AgentProvider(row["agent_type"]),
            type=row.get("type") or "oauth",
            label=row["label"],
            credentials=_decrypt_credentials(row.get("credentials")),
            token_limit=row["token_limit"],
            enabled=bool(row["enabled"]),
            status=TokenStatus(row.get("status", "ok") or "ok"),
            priority=int(row.get("priority") or 0),
            error_msg=row.get("error_msg"),
            expires_at=row.get("expires_at"),
            used_at=row.get("used_at"),
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
