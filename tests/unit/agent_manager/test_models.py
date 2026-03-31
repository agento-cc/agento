from __future__ import annotations

from datetime import datetime, timezone

from agento.framework.agent_manager.models import AgentProvider, RotationResult, Token, UsageSummary


class TestAgentProvider:
    def test_claude_value(self):
        assert AgentProvider.CLAUDE.value == "claude"

    def test_codex_value(self):
        assert AgentProvider.CODEX.value == "codex"

    def test_from_string(self):
        assert AgentProvider("claude") == AgentProvider.CLAUDE
        assert AgentProvider("codex") == AgentProvider.CODEX


class TestToken:
    def test_from_row(self):
        row = {
            "id": 1,
            "agent_type": "claude",
            "label": "prod-1",
            "credentials_path": "/etc/tokens/claude_1.json",
            "model": "claude-sonnet-4-20250514",
            "is_primary": 1,
            "token_limit": 100000,
            "enabled": 1,
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.id == 1
        assert token.agent_type == AgentProvider.CLAUDE
        assert token.label == "prod-1"
        assert token.credentials_path == "/etc/tokens/claude_1.json"
        assert token.model == "claude-sonnet-4-20250514"
        assert token.is_primary is True
        assert token.token_limit == 100000
        assert token.enabled is True

    def test_from_row_disabled(self):
        row = {
            "id": 2,
            "agent_type": "codex",
            "label": "codex-1",
            "credentials_path": "/etc/tokens/codex_1.json",
            "model": None,
            "is_primary": 0,
            "token_limit": 0,
            "enabled": 0,
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.agent_type == AgentProvider.CODEX
        assert token.enabled is False
        assert token.token_limit == 0
        assert token.model is None
        assert token.is_primary is False

    def test_from_row_defaults_missing_model_and_primary(self):
        row = {
            "id": 3,
            "agent_type": "claude",
            "label": "legacy",
            "credentials_path": "/etc/tokens/old.json",
            "token_limit": 50000,
            "enabled": 1,
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
        }

        token = Token.from_row(row)

        assert token.model is None
        assert token.is_primary is False


class TestUsageSummary:
    def test_creation(self):
        summary = UsageSummary(token_id=1, total_tokens=50000, call_count=10)
        assert summary.token_id == 1
        assert summary.total_tokens == 50000
        assert summary.call_count == 10


class TestRotationResult:
    def test_creation(self):
        now = datetime.now(timezone.utc)
        result = RotationResult(
            agent_type=AgentProvider.CLAUDE,
            previous_token_id=1,
            new_token_id=2,
            reason="rotation",
            timestamp=now,
        )
        assert result.agent_type == AgentProvider.CLAUDE
        assert result.previous_token_id == 1
        assert result.new_token_id == 2
        assert result.reason == "rotation"

    def test_initial_rotation(self):
        result = RotationResult(
            agent_type=AgentProvider.CODEX,
            previous_token_id=None,
            new_token_id=1,
            reason="initial",
            timestamp=datetime.now(timezone.utc),
        )
        assert result.previous_token_id is None
