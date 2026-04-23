from __future__ import annotations

import json
from datetime import datetime

import pytest

from agento.framework.agent_manager.models import (
    AgentProvider,
    Token,
    TokenStatus,
    UsageSummary,
)


class _FakeEncryptor:
    def encrypt(self, plaintext: str) -> str:
        return f"aes256:iv:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.split(":", 2)[-1]


@pytest.fixture(autouse=True)
def _fake_encryptor(monkeypatch):
    from agento.framework import encryptor as enc
    monkeypatch.setattr(enc, "_instance", _FakeEncryptor())
    yield


_CREDS = {"subscription_key": "sk-test"}
_CIPHERTEXT = f"aes256:iv:{json.dumps(_CREDS)}"


class TestAgentProvider:
    def test_claude_value(self):
        assert AgentProvider.CLAUDE.value == "claude"

    def test_codex_value(self):
        assert AgentProvider.CODEX.value == "codex"

    def test_from_string(self):
        assert AgentProvider("claude") == AgentProvider.CLAUDE
        assert AgentProvider("codex") == AgentProvider.CODEX


class TestTokenStatus:
    def test_values(self):
        assert TokenStatus.OK.value == "ok"
        assert TokenStatus.ERROR.value == "error"


class TestToken:
    def test_from_row(self):
        row = {
            "id": 1,
            "agent_type": "claude",
            "label": "prod-1",
            "credentials": _CIPHERTEXT,
            "model": "claude-sonnet-4-20250514",
            "token_limit": 100000,
            "enabled": 1,
            "status": "ok",
            "error_msg": None,
            "expires_at": datetime(2026, 1, 1),
            "used_at": datetime(2025, 12, 31),
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.id == 1
        assert token.agent_type == AgentProvider.CLAUDE
        assert token.label == "prod-1"
        assert token.credentials == _CREDS
        assert token.model == "claude-sonnet-4-20250514"
        assert token.token_limit == 100000
        assert token.enabled is True
        assert token.status == TokenStatus.OK
        assert token.error_msg is None
        assert token.expires_at == datetime(2026, 1, 1)
        assert token.used_at == datetime(2025, 12, 31)

    def test_from_row_errored(self):
        row = {
            "id": 2,
            "agent_type": "codex",
            "label": "codex-1",
            "credentials": None,
            "model": None,
            "token_limit": 0,
            "enabled": 0,
            "status": "error",
            "error_msg": "OAuth token expired",
            "expires_at": None,
            "used_at": None,
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.agent_type == AgentProvider.CODEX
        assert token.enabled is False
        assert token.token_limit == 0
        assert token.model is None
        assert token.status == TokenStatus.ERROR
        assert token.error_msg == "OAuth token expired"
        assert token.expires_at is None
        assert token.used_at is None
        assert token.credentials is None

    def test_from_row_defaults_missing_health_fields(self):
        row = {
            "id": 3,
            "agent_type": "claude",
            "label": "legacy",
            "credentials": _CIPHERTEXT,
            "token_limit": 50000,
            "enabled": 1,
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.model is None
        assert token.status == TokenStatus.OK
        assert token.error_msg is None
        assert token.expires_at is None
        assert token.used_at is None


class TestUsageSummary:
    def test_creation(self):
        summary = UsageSummary(token_id=1, total_tokens=50000, call_count=10)
        assert summary.token_id == 1
        assert summary.total_tokens == 50000
        assert summary.call_count == 10
