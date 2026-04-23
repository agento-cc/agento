from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.token_resolver import TokenResolver

from .conftest import make_token


class TestTokenResolver:
    def test_resolve_returns_whatever_select_token_yields(self):
        expected = make_token(id=2)

        with patch(
            "agento.framework.agent_manager.token_resolver.select_token",
            return_value=expected,
        ) as mock_select:
            resolver = TokenResolver()
            token = resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

        assert token is expected
        mock_select.assert_called_once()
        assert mock_select.call_args[0][1] == AgentProvider.CLAUDE

    def test_resolve_raises_when_no_tokens_registered(self):
        with (
            patch(
                "agento.framework.agent_manager.token_resolver.select_token",
                return_value=None,
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.count_tokens_for_provider",
                return_value=(0, 0),
            ),
        ):
            resolver = TokenResolver()
            with pytest.raises(RuntimeError, match="No enabled tokens"):
                resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

    def test_resolve_raises_when_all_errored_or_expired(self):
        with (
            patch(
                "agento.framework.agent_manager.token_resolver.select_token",
                return_value=None,
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.count_tokens_for_provider",
                return_value=(3, 0),
            ),
        ):
            resolver = TokenResolver()
            with pytest.raises(RuntimeError, match=r"3 enabled tokens.*unhealthy"):
                resolver.resolve(MagicMock(), AgentProvider.CODEX)

    def test_resolve_error_mentions_recovery_commands(self):
        with (
            patch(
                "agento.framework.agent_manager.token_resolver.select_token",
                return_value=None,
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.count_tokens_for_provider",
                return_value=(2, 0),
            ),
        ):
            resolver = TokenResolver()
            with pytest.raises(RuntimeError) as exc_info:
                resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

        msg = str(exc_info.value)
        assert "token:refresh" in msg
        assert "token:reset" in msg

    def test_resolve_passes_provider_through(self):
        with patch(
            "agento.framework.agent_manager.token_resolver.select_token",
            return_value=make_token(id=1, agent_type=AgentProvider.CODEX),
        ) as mock_select:
            resolver = TokenResolver()
            resolver.resolve(MagicMock(), AgentProvider.CODEX)

        assert mock_select.call_args[0][1] == AgentProvider.CODEX
