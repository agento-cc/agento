from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agento.framework.agent_manager.config import AgentManagerConfig
from agento.framework.agent_manager.models import AgentProvider, Token, UsageSummary


@pytest.fixture
def agent_config(tmp_path):
    """AgentManagerConfig pointing to tmp_path for filesystem tests."""
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    active_dir = tokens_dir / "active"
    active_dir.mkdir()
    return AgentManagerConfig(
        tokens_dir=str(tokens_dir),
        active_dir=str(active_dir),
    )


def make_token(
    *,
    id: int = 1,
    agent_type: AgentProvider = AgentProvider.CLAUDE,
    label: str = "test-token",
    credentials_path: str = "/etc/tokens/test.json",
    model: str | None = None,
    is_primary: bool = False,
    token_limit: int = 100_000,
    enabled: bool = True,
) -> Token:
    """Helper to create Token instances for testing."""
    now = datetime.now(UTC)
    return Token(
        id=id,
        agent_type=agent_type,
        label=label,
        credentials_path=credentials_path,
        model=model,
        is_primary=is_primary,
        token_limit=token_limit,
        enabled=enabled,
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
