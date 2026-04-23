"""Tests for cmd_token_refresh — interactive OAuth re-authentication."""
from __future__ import annotations

import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.auth import AuthenticationError, AuthResult
from agento.framework.agent_manager.config import AgentManagerConfig
from agento.framework.agent_manager.models import AgentProvider, Token
from agento.framework.consumer_config import ConsumerConfig
from agento.framework.database_config import DatabaseConfig

# Patch targets (lazy imports inside cmd_token_refresh)
_P_GET_TOKEN = "agento.framework.agent_manager.token_store.get_token"
_P_AUTH = "agento.framework.agent_manager.auth.authenticate_interactive"
_P_REGISTER = "agento.framework.agent_manager.register_token"
_P_GET_CONN = "agento.framework.cli.token.get_connection_or_exit"
_FRAMEWORK_CFG = (DatabaseConfig(), ConsumerConfig(), AgentManagerConfig())


def _make_args(token_id: int) -> argparse.Namespace:
    return argparse.Namespace(token_id=token_id)


_NOW = datetime(2026, 1, 1)


def _make_token(
    id: int = 2,
    agent_type: str = "codex",
    label: str = "codex-team",
    enabled: bool = True,
) -> Token:
    from agento.framework.agent_manager.models import TokenStatus
    return Token(
        id=id,
        agent_type=AgentProvider(agent_type),
        label=label,
        credentials={"subscription_key": "sk-existing"},
        token_limit=0,
        model=None,
        enabled=enabled,
        status=TokenStatus.OK,
        error_msg=None,
        expires_at=None,
        used_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


_AUTH_RESULT = AuthResult(
    subscription_key="new-access-token",
    refresh_token="new-refresh-token",
    expires_at=None,
    subscription_type=None,
    id_token="new-id-token",
    raw_auth={"tokens": {"access_token": "new-access-token"}},
)


@patch("agento.framework.cli.token.get_logger", return_value=MagicMock())
@patch("agento.framework.cli.token._load_framework_config", return_value=_FRAMEWORK_CFG)
@patch(_P_GET_CONN)
class TestTokenRefresh:
    """cmd_token_refresh tests."""

    def test_refresh_success(self, mock_conn_fn, mock_config, mock_logger):
        token = _make_token()
        mock_conn_fn.return_value = MagicMock()

        with (
            patch(_P_GET_TOKEN, return_value=token),
            patch("sys.stdin") as mock_stdin,
            patch(_P_AUTH, return_value=_AUTH_RESULT) as mock_auth,
            patch(_P_REGISTER, return_value=token) as mock_register,
        ):
            mock_stdin.isatty.return_value = True
            from agento.framework.cli.token import TokenRefreshCommand
            TokenRefreshCommand().execute(_make_args(2))

        mock_auth.assert_called_once_with(AgentProvider.CODEX, mock_logger.return_value)
        # register_token called with new credentials derived from auth result
        mock_register.assert_called_once()
        kwargs = mock_register.call_args.kwargs
        assert kwargs["label"] == token.label
        assert kwargs["agent_type"] == token.agent_type
        assert kwargs["credentials"]["subscription_key"] == "new-access-token"

    def test_refresh_not_found(self, mock_conn_fn, mock_config, mock_logger):
        mock_conn_fn.return_value = MagicMock()

        with (
            patch(_P_GET_TOKEN, return_value=None),
            pytest.raises(SystemExit, match="1"),
        ):
            from agento.framework.cli.token import TokenRefreshCommand
            TokenRefreshCommand().execute(_make_args(99))

    def test_refresh_disabled_token(self, mock_conn_fn, mock_config, mock_logger):
        token = _make_token(enabled=False)
        mock_conn_fn.return_value = MagicMock()

        with (
            patch(_P_GET_TOKEN, return_value=token),
            pytest.raises(SystemExit, match="1"),
        ):
            from agento.framework.cli.token import TokenRefreshCommand
            TokenRefreshCommand().execute(_make_args(2))

    def test_refresh_no_tty(self, mock_conn_fn, mock_config, mock_logger):
        token = _make_token()
        mock_conn_fn.return_value = MagicMock()

        with (
            patch(_P_GET_TOKEN, return_value=token),
            patch("sys.stdin") as mock_stdin,
            pytest.raises(SystemExit, match="1"),
        ):
            mock_stdin.isatty.return_value = False
            from agento.framework.cli.token import TokenRefreshCommand
            TokenRefreshCommand().execute(_make_args(2))

    def test_refresh_auth_failure(self, mock_conn_fn, mock_config, mock_logger):
        token = _make_token()
        mock_conn_fn.return_value = MagicMock()

        with (
            patch(_P_GET_TOKEN, return_value=token),
            patch("sys.stdin") as mock_stdin,
            patch(_P_AUTH, side_effect=AuthenticationError("cancelled")),
            pytest.raises(SystemExit, match="1"),
        ):
            mock_stdin.isatty.return_value = True
            from agento.framework.cli.token import TokenRefreshCommand
            TokenRefreshCommand().execute(_make_args(2))
