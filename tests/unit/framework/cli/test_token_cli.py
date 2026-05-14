"""Tests for the token:* CLI commands — specifically that ``token:mark-error``
dispatches ``token_auth_failed_after`` so workspace builds get re-materialized
with the next healthy token's credentials."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_manager.models import AgentProvider, Token, TokenStatus
from agento.framework.cli.token import TokenMarkErrorCommand


def _make_args(token_id: int = 6, message: str = "refresh-failed"):
    return argparse.Namespace(token_id=token_id, message=message)


def _make_token(agent_type: AgentProvider = AgentProvider.CODEX, token_id: int = 6) -> Token:
    now = datetime.now(UTC).replace(tzinfo=None)
    return Token(
        id=token_id,
        agent_type=agent_type,
        label="client-it@example.com",
        credentials={"subscription_key": "sk-broken"},
        model=None,
        token_limit=0,
        enabled=True,
        status=TokenStatus.ERROR,
        error_msg=None,
        expires_at=None,
        used_at=None,
        created_at=now,
        updated_at=now,
    )


class TestTokenMarkErrorCommand:
    @patch("agento.framework.cli.token.get_connection_or_exit")
    @patch("agento.framework.cli.token._load_framework_config")
    @patch("agento.framework.agent_manager.token_store.get_token")
    @patch("agento.framework.agent_manager.mark_token_error")
    @patch("agento.framework.event_manager.get_event_manager")
    def test_dispatches_token_auth_failed_after_on_success(
        self,
        mock_get_events,
        mock_mark,
        mock_get_token,
        mock_config,
        mock_conn_fn,
    ):
        mock_config.return_value = ({}, None, None)
        mock_conn_fn.return_value = MagicMock()
        mock_get_token.return_value = _make_token()
        mock_mark.return_value = True
        events = MagicMock()
        mock_get_events.return_value = events

        TokenMarkErrorCommand().execute(_make_args())

        events.dispatch.assert_called_once()
        event_name, payload = events.dispatch.call_args.args
        assert event_name == "token_auth_failed_after"
        assert payload.agent_type == "codex"
        assert payload.token_id == 6
        assert payload.error_msg == "refresh-failed"
        assert payload.job_id is None

    @patch("agento.framework.cli.token.get_connection_or_exit")
    @patch("agento.framework.cli.token._load_framework_config")
    @patch("agento.framework.agent_manager.token_store.get_token")
    @patch("agento.framework.agent_manager.mark_token_error")
    @patch("agento.framework.event_manager.get_event_manager")
    def test_does_not_dispatch_when_token_missing(
        self,
        mock_get_events,
        mock_mark,
        mock_get_token,
        mock_config,
        mock_conn_fn,
    ):
        mock_config.return_value = ({}, None, None)
        mock_conn_fn.return_value = MagicMock()
        mock_get_token.return_value = None
        mock_mark.return_value = False
        events = MagicMock()
        mock_get_events.return_value = events

        with pytest.raises(SystemExit):
            TokenMarkErrorCommand().execute(_make_args())

        events.dispatch.assert_not_called()
