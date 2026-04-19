from __future__ import annotations

from unittest.mock import MagicMock, patch

from agento.framework.agent_manager.active import (
    resolve_active_token,
    update_active_token,
)
from agento.framework.agent_manager.models import AgentProvider

from .conftest import make_token


class TestResolveActiveToken:
    def test_returns_none_when_no_primary(self):
        conn = MagicMock()
        with patch(
            "agento.framework.agent_manager.active.get_primary_token",
            return_value=None,
        ):
            assert resolve_active_token(conn, AgentProvider.CLAUDE) is None

    def test_returns_primary_token(self):
        conn = MagicMock()
        token = make_token(is_primary=True)
        with patch(
            "agento.framework.agent_manager.active.get_primary_token",
            return_value=token,
        ) as mock_get:
            result = resolve_active_token(conn, AgentProvider.CLAUDE)
        assert result is token
        mock_get.assert_called_once_with(conn, AgentProvider.CLAUDE)


class TestUpdateActiveToken:
    def test_sets_primary_in_db(self):
        conn = MagicMock()
        token = make_token(id=7, agent_type=AgentProvider.CODEX)
        with patch(
            "agento.framework.agent_manager.active.set_primary_token",
        ) as mock_set:
            update_active_token(conn, AgentProvider.CODEX, token)
        mock_set.assert_called_once()
        args, _kwargs = mock_set.call_args
        assert args[0] is conn
        assert args[1] == AgentProvider.CODEX
        assert args[2] == 7
