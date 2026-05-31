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
from agento.framework.config_writer import (
    clear as _clear_config_writers,
)
from agento.framework.config_writer import (
    register_config_writer,
)
from agento.modules.claude.src.config import ClaudeConfigWriter
from agento.modules.codex.src.config import CodexConfigWriter


@pytest.fixture(autouse=True)
def _register_config_writers():
    """Register provider ConfigWriters so ``TokenRunner._build_env`` (which now
    delegates to ``ConfigWriter.credential_env``) can resolve them in unit
    tests that don't run the full ``bootstrap()`` module loader.
    """
    _clear_config_writers()
    register_config_writer(AgentProvider.CLAUDE, ClaudeConfigWriter())
    register_config_writer(AgentProvider.CODEX, CodexConfigWriter())
    yield
    _clear_config_writers()


@pytest.fixture
def agent_config(tmp_path):
    """AgentManagerConfig for tests that still need one."""
    return AgentManagerConfig()


def make_token(
    *,
    id: int = 1,
    agent_type: AgentProvider = AgentProvider.CLAUDE,
    type: str = "oauth",
    label: str = "test-token",
    credentials: dict | None = None,
    token_limit: int = 100_000,
    enabled: bool = True,
    status: TokenStatus = TokenStatus.OK,
    priority: int = 0,
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
        type=type,
        label=label,
        credentials=credentials,
        token_limit=token_limit,
        enabled=enabled,
        status=status,
        priority=priority,
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
