from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.config import AgentManagerConfig
from agento.framework.agent_manager.models import AgentProvider
from agento.framework.agent_manager.token_resolver import TokenResolver

from .conftest import make_token, make_usage


class TestTokenResolver:
    def test_resolve_returns_best_token(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=100_000)

        with (
            patch(
                "agento.framework.agent_manager.token_resolver.list_tokens",
                return_value=[t1, t2],
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.get_usage_summaries",
                return_value=[
                    make_usage(1, total_tokens=80_000, call_count=10),
                    make_usage(2, total_tokens=20_000, call_count=5),
                ],
            ),
        ):
            resolver = TokenResolver()
            token = resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

        assert token.id == 2  # more capacity remaining

    def test_resolve_raises_when_no_tokens(self):
        with patch(
            "agento.framework.agent_manager.token_resolver.list_tokens",
            return_value=[],
        ):
            resolver = TokenResolver()
            with pytest.raises(RuntimeError, match="No enabled tokens"):
                resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

    def test_resolve_single_token(self):
        t1 = make_token(id=1)

        with (
            patch(
                "agento.framework.agent_manager.token_resolver.list_tokens",
                return_value=[t1],
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.get_usage_summaries",
                return_value=[],
            ),
        ):
            resolver = TokenResolver()
            token = resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

        assert token.id == 1

    def test_resolve_uses_config_window_hours(self):
        t1 = make_token(id=1)
        config = AgentManagerConfig(usage_window_hours=48)

        with (
            patch(
                "agento.framework.agent_manager.token_resolver.list_tokens",
                return_value=[t1],
            ),
            patch(
                "agento.framework.agent_manager.token_resolver.get_usage_summaries",
                return_value=[],
            ) as mock_usage,
        ):
            resolver = TokenResolver(config=config)
            resolver.resolve(MagicMock(), AgentProvider.CLAUDE)

        mock_usage.assert_called_once()
        assert mock_usage.call_args[0][2] == 48

    def test_resolve_filters_by_provider(self):
        t1 = make_token(id=1, agent_type=AgentProvider.CODEX)

        with (
            patch(
                "agento.framework.agent_manager.token_resolver.list_tokens",
                return_value=[t1],
            ) as mock_list,
            patch(
                "agento.framework.agent_manager.token_resolver.get_usage_summaries",
                return_value=[],
            ),
        ):
            resolver = TokenResolver()
            resolver.resolve(MagicMock(), AgentProvider.CODEX)

        mock_list.assert_called_once_with(
            mock_list.call_args[0][0],
            agent_type=AgentProvider.CODEX,
            enabled_only=True,
        )
