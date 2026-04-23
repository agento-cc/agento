from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agento.framework.agent_manager.config import AgentManagerConfig
from agento.framework.agent_manager.models import (
    AgentProvider,
    Token,
    TokenStatus,
    UsageSummary,
)


@pytest.fixture
def agent_config(tmp_path):
    """AgentManagerConfig for tests that still need one."""
    return AgentManagerConfig()


def make_token(
    *,
    id: int = 1,
    agent_type: AgentProvider = AgentProvider.CLAUDE,
    label: str = "test-token",
    credentials: dict | None = None,
    model: str | None = None,
    token_limit: int = 100_000,
    enabled: bool = True,
    status: TokenStatus = TokenStatus.OK,
    error_msg: str | None = None,
    expires_at: datetime | None = None,
    used_at: datetime | None = None,
) -> Token:
    """Helper to create Token instances for testing."""
    now = datetime.now(UTC)
    if credentials is None:
        credentials = {"subscription_key": "sk-test"}
    return Token(
        id=id,
        agent_type=agent_type,
        label=label,
        credentials=credentials,
        model=model,
        token_limit=token_limit,
        enabled=enabled,
        status=status,
        error_msg=error_msg,
        expires_at=expires_at,
        used_at=used_at,
        created_at=now,
        updated_at=now,
    )


def make_usage(
    token_id: int,
    total_tokens: int = 0,
    call_count: int = 0,
) -> UsageSummary:
    """Helper to create UsageSummary instances for testing."""
    return UsageSummary(
        token_id=token_id,
        total_tokens=total_tokens,
        call_count=call_count,
    )
