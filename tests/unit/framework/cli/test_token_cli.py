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
        type="oauth",
        label="client-it@example.com",
        credentials={"subscription_key": "sk-broken"},
        model=None,
        token_limit=0,
        enabled=True,
        status=TokenStatus.ERROR,
        priority=0,
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


class TestWithAccessToken:
    def test_codex_dispatches_to_register_from_access_token(self):
        from agento.framework.agent_manager.models import AgentProvider
        from agento.framework.cli.token import _resolve_credentials

        args = argparse.Namespace(
            agent_type="codex", label="my-at",
            with_api_key=None, with_access_token="eyJ.payload.sig",
            token_limit=0, model=None,
        )
        strategy = MagicMock()
        strategy.register_from_access_token.return_value = {
            "access_token": "eyJ.payload.sig", "expires_at": 9999999999}
        with patch("agento.framework.agent_manager.auth.get_auth_strategy", return_value=strategy):
            creds, type_ = _resolve_credentials(args, AgentProvider.CODEX, MagicMock())

        strategy.register_from_access_token.assert_called_once_with("eyJ.payload.sig")
        assert type_ == "codex_access_token"
        assert creds["access_token"] == "eyJ.payload.sig"


class TestWithApiKey:
    def test_codex_dispatches_with_openai_api_key_type(self):
        from agento.framework.agent_manager.models import AgentProvider
        from agento.framework.cli.token import _resolve_credentials

        args = argparse.Namespace(
            agent_type="codex", label="my-ak",
            with_api_key="sk-X", with_access_token=None,
            token_limit=0, model=None,
        )
        strategy = MagicMock()
        strategy.register_from_api_key.return_value = {"api_key": "sk-X"}
        with patch("agento.framework.agent_manager.auth.get_auth_strategy", return_value=strategy):
            _creds, type_ = _resolve_credentials(args, AgentProvider.CODEX, MagicMock())

        strategy.register_from_api_key.assert_called_once_with("sk-X")
        assert type_ == "openai_api_key"

    def test_claude_dispatches_with_anthropic_api_key_type(self):
        from agento.framework.agent_manager.models import AgentProvider
        from agento.framework.cli.token import _resolve_credentials

        args = argparse.Namespace(
            agent_type="claude", label="my-ak",
            with_api_key="sk-ant-X", with_access_token=None,
            token_limit=0, model=None,
        )
        strategy = MagicMock()
        strategy.register_from_api_key.return_value = {"api_key": "sk-ant-X"}
        with patch("agento.framework.agent_manager.auth.get_auth_strategy", return_value=strategy):
            _creds, type_ = _resolve_credentials(args, AgentProvider.CLAUDE, MagicMock())
        assert type_ == "anthropic_api_key"


class TestMutualExclusion:
    def test_argparse_rejects_both_flags(self):
        from agento.framework.cli.token import TokenRegisterCommand
        parser = argparse.ArgumentParser()
        TokenRegisterCommand().configure(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["codex", "lbl", "--with-api-key", "X", "--with-access-token", "Y"])


class TestPositionalRemoved:
    def test_positional_credentials_path_no_longer_accepted(self):
        from agento.framework.cli.token import TokenRegisterCommand
        parser = argparse.ArgumentParser()
        TokenRegisterCommand().configure(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["codex", "lbl", "/path/to/creds.json"])


class TestSetPriorityCommand:
    def test_set_priority_dispatches_to_store(self, capsys):
        from agento.framework.cli.token import TokenSetPriorityCommand
        args = argparse.Namespace(token_id=42, priority=5)
        with patch("agento.framework.cli.token._load_framework_config",
                   return_value=(MagicMock(), MagicMock(), MagicMock())), \
             patch("agento.framework.cli.token.get_connection_or_exit",
                   return_value=MagicMock()), \
             patch("agento.framework.agent_manager.token_store.set_token_priority",
                   return_value=True) as mock_set:
            TokenSetPriorityCommand().execute(args)
        mock_set.assert_called_once()
        # set_token_priority(conn, token_id, priority, logger=...)
        call_args = mock_set.call_args
        assert call_args.args[1] == 42 and call_args.args[2] == 5

    def test_set_priority_errors_when_token_missing(self, capsys):
        from agento.framework.cli.token import TokenSetPriorityCommand
        args = argparse.Namespace(token_id=999, priority=1)
        with patch("agento.framework.cli.token._load_framework_config",
                   return_value=(MagicMock(), MagicMock(), MagicMock())), \
             patch("agento.framework.cli.token.get_connection_or_exit",
                   return_value=MagicMock()), \
             patch("agento.framework.agent_manager.token_store.set_token_priority",
                   return_value=False), \
             pytest.raises(SystemExit):
            TokenSetPriorityCommand().execute(args)

    def test_set_priority_configure_accepts_int_args(self):
        from agento.framework.cli.token import TokenSetPriorityCommand
        parser = argparse.ArgumentParser()
        TokenSetPriorityCommand().configure(parser)
        ns = parser.parse_args(["42", "5"])
        assert ns.token_id == 42 and ns.priority == 5


class TestTokenListShowsTypeAndPriority:
    def _token(self, id_, type_, priority):
        from datetime import datetime

        from agento.framework.agent_manager.models import (
            AgentProvider,
            Token,
            TokenStatus,
        )
        return Token(
            id=id_, agent_type=AgentProvider.CODEX, type=type_, label=f"t{id_}",
            credentials=None, model=None, token_limit=0, enabled=True,
            status=TokenStatus.OK, priority=priority, error_msg=None,
            expires_at=None, used_at=None,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )

    def test_json_output_includes_type_and_priority(self, capsys):
        import json

        from agento.framework.cli.token import TokenListCommand

        tokens = [self._token(1, "codex_access_token", 5), self._token(2, "oauth", 0)]
        args = argparse.Namespace(agent_type=None, all=False, json=True)
        with patch("agento.framework.cli.token._load_framework_config",
                   return_value=(MagicMock(), MagicMock(), MagicMock(usage_window_hours=24))), \
             patch("agento.framework.cli.token.get_connection_or_exit"), \
             patch("agento.framework.agent_manager.list_tokens", return_value=tokens), \
             patch("agento.framework.agent_manager.get_usage_summaries", return_value=[]):
            TokenListCommand().execute(args)

        out = json.loads(capsys.readouterr().out)
        by_id = {r["id"]: r for r in out}
        assert by_id[1]["type"] == "codex_access_token"
        assert by_id[1]["priority"] == 5
        assert by_id[2]["type"] == "oauth"
        assert by_id[2]["priority"] == 0

    def test_text_output_includes_type_and_priority(self, capsys):
        from agento.framework.cli.token import TokenListCommand

        tokens = [self._token(1, "codex_access_token", 5)]
        args = argparse.Namespace(agent_type=None, all=False, json=False)
        with patch("agento.framework.cli.token._load_framework_config",
                   return_value=(MagicMock(), MagicMock(), MagicMock(usage_window_hours=24))), \
             patch("agento.framework.cli.token.get_connection_or_exit"), \
             patch("agento.framework.agent_manager.list_tokens", return_value=tokens), \
             patch("agento.framework.agent_manager.get_usage_summaries", return_value=[]):
            TokenListCommand().execute(args)
        out = capsys.readouterr().out
        assert "type=codex_access_token" in out
        assert "priority=5" in out


class TestTokenRegisterEventCarriesType:
    """token:register dispatches TokenRegisteredEvent with the correct type field."""

    def _make_registered_token(self, type_: str) -> Token:
        now = datetime.now(UTC).replace(tzinfo=None)
        return Token(
            id=7,
            agent_type=AgentProvider.CODEX,
            type=type_,
            label="my-label",
            credentials={"api_key": "sk-X"},
            model=None,
            token_limit=0,
            enabled=True,
            status=TokenStatus.OK,
            priority=0,
            error_msg=None,
            expires_at=None,
            used_at=None,
            created_at=now,
            updated_at=now,
        )

    @patch("agento.framework.cli.token.get_connection_or_exit")
    @patch("agento.framework.cli.token._load_framework_config")
    @patch("agento.framework.cli.token._resolve_credentials")
    @patch("agento.framework.agent_manager.register_token")
    @patch("agento.framework.event_manager.get_event_manager")
    def test_dispatched_event_carries_openai_api_key_type(
        self,
        mock_get_events,
        mock_register,
        mock_resolve,
        mock_config,
        mock_conn_fn,
    ):
        from agento.framework.cli.token import TokenRegisterCommand

        mock_config.return_value = ({}, None, None)
        conn = MagicMock()
        mock_conn_fn.return_value = conn
        mock_resolve.return_value = ({"api_key": "sk-X"}, "openai_api_key")
        mock_register.return_value = self._make_registered_token("openai_api_key")
        events = MagicMock()
        mock_get_events.return_value = events

        args = argparse.Namespace(
            agent_type="codex",
            label="my-label",
            with_api_key="sk-X",
            with_access_token=None,
            token_limit=0,
            model=None,
        )
        TokenRegisterCommand().execute(args)

        events.dispatch.assert_called_once()
        _event_name, payload = events.dispatch.call_args.args
        assert payload.type == "openai_api_key"
        assert payload.token_id == 7
        assert payload.agent_type == "codex"

    @patch("agento.framework.cli.token.get_connection_or_exit")
    @patch("agento.framework.cli.token._load_framework_config")
    @patch("agento.framework.cli.token._resolve_credentials")
    @patch("agento.framework.agent_manager.register_token")
    @patch("agento.framework.event_manager.get_event_manager")
    def test_dispatched_event_carries_oauth_type_for_interactive_flow(
        self,
        mock_get_events,
        mock_register,
        mock_resolve,
        mock_config,
        mock_conn_fn,
    ):
        from agento.framework.cli.token import TokenRegisterCommand

        mock_config.return_value = ({}, None, None)
        conn = MagicMock()
        mock_conn_fn.return_value = conn
        mock_resolve.return_value = ({"subscription_key": "sk-new"}, "oauth")
        mock_register.return_value = self._make_registered_token("oauth")
        events = MagicMock()
        mock_get_events.return_value = events

        args = argparse.Namespace(
            agent_type="codex",
            label="my-label",
            with_api_key=None,
            with_access_token=None,
            token_limit=0,
            model=None,
        )
        TokenRegisterCommand().execute(args)

        events.dispatch.assert_called_once()
        _event_name, payload = events.dispatch.call_args.args
        assert payload.type == "oauth"
