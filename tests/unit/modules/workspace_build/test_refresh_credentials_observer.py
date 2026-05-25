"""Tests for RefreshBuildCredentialsObserver — keeps existing build dirs in
sync with oauth_token after ``token:refresh`` / ``token:register``."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agento.framework.agent_manager.models import Token
from agento.modules.workspace_build.src.observers import (
    RefreshBuildCredentialsObserver,
)


@pytest.fixture
def build_root(tmp_path, monkeypatch):
    base = tmp_path / "workspace" / "build"
    base.mkdir(parents=True)
    monkeypatch.setattr(
        "agento.modules.workspace_build.src.observers.BUILD_DIR", str(base),
    )
    return base


def _make_build(base, ws: str, av: str, build_id: int = 1):
    """Create ``<ws>/<av>/builds/<n>`` and a ``current`` symlink pointing to it."""
    build_dir = base / ws / av / "builds" / str(build_id)
    build_dir.mkdir(parents=True)
    current = base / ws / av / "current"
    current.symlink_to(build_dir)
    return build_dir


def _make_event(agent_type="claude", credentials=None, type_="oauth"):
    event = MagicMock()
    event.agent_type = agent_type
    event.credentials = credentials or {"subscription_key": "sk-new"}
    event.type = type_
    return event


class TestRefreshObserver:
    def test_writes_credentials_into_every_current_build(self, build_root, monkeypatch):
        zyga = _make_build(build_root, "default", "zyga")
        mieszko = _make_build(build_root, "default", "mieszko")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        event = _make_event(credentials={"subscription_key": "sk-new"})
        RefreshBuildCredentialsObserver().execute(event)

        called_dirs = {call.args[0] for call in writer.write_credentials.call_args_list}
        assert called_dirs == {zyga, mieszko}
        for call in writer.write_credentials.call_args_list:
            token = call.args[1]
            assert isinstance(token, Token)
            assert token.credentials == {"subscription_key": "sk-new"}

    def test_only_touches_writer_for_event_provider(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        claude_writer = MagicMock()
        codex_writer = MagicMock()

        def _fake_get(provider):
            if provider == "claude":
                return claude_writer
            return codex_writer

        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            _fake_get,
        )

        RefreshBuildCredentialsObserver().execute(_make_event(agent_type="claude"))

        assert claude_writer.write_credentials.call_count == 1
        codex_writer.write_credentials.assert_not_called()

    def test_skips_when_no_provider(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        event = MagicMock()
        event.agent_type = None
        event.credentials = {"subscription_key": "sk-new"}

        RefreshBuildCredentialsObserver().execute(event)

        writer.write_credentials.assert_not_called()

    def test_skips_when_writer_not_registered(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        def _raise(_provider):
            raise KeyError("no writer")

        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            _raise,
        )

        RefreshBuildCredentialsObserver().execute(_make_event())  # must not raise

    def test_skips_dangling_current_symlink(self, build_root, monkeypatch):
        current = build_root / "default" / "ghost" / "current"
        current.parent.mkdir(parents=True)
        current.symlink_to(build_root / "default" / "ghost" / "builds" / "999")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        RefreshBuildCredentialsObserver().execute(_make_event())

        writer.write_credentials.assert_not_called()

    def test_keeps_iterating_when_one_build_fails(self, build_root, monkeypatch):
        zyga = _make_build(build_root, "default", "zyga")
        mieszko = _make_build(build_root, "default", "mieszko")

        writer = MagicMock()
        writer.write_credentials.side_effect = [OSError("boom"), None]
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        RefreshBuildCredentialsObserver().execute(_make_event())

        called = {call.args[0] for call in writer.write_credentials.call_args_list}
        assert called == {zyga, mieszko}

    def test_no_build_root_is_noop(self, tmp_path, monkeypatch):
        missing = tmp_path / "no" / "workspace" / "build"
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.BUILD_DIR", str(missing),
        )
        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        RefreshBuildCredentialsObserver().execute(_make_event())

        writer.write_credentials.assert_not_called()

    def test_token_type_propagated_from_event(self, build_root, monkeypatch):
        """Token built from a TokenRegisteredEvent carries the event's type field."""
        from agento.modules.workspace_build.src.observers import _token_from_event

        event = _make_event(agent_type="claude", type_="codex_access_token")
        token = _token_from_event(event)
        assert token.type == "codex_access_token"

    def test_token_type_defaults_to_oauth_when_absent(self, build_root, monkeypatch):
        """Events without a type attribute fall back to 'oauth'."""
        from unittest.mock import MagicMock

        from agento.modules.workspace_build.src.observers import _token_from_event

        event = MagicMock(spec=["agent_type", "token_id", "label", "credentials"])
        event.agent_type = "claude"
        event.token_id = 1
        event.label = "test"
        event.credentials = {}
        token = _token_from_event(event)
        assert token.type == "oauth"

    def test_token_type_openai_api_key_propagated(self, build_root, monkeypatch):
        """A freshly-registered openai_api_key token is correctly threaded into builds."""
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        event = _make_event(
            agent_type="codex",
            credentials={"api_key": "sk-openai"},
            type_="openai_api_key",
        )
        RefreshBuildCredentialsObserver().execute(event)

        assert writer.write_credentials.call_count == 1
        token = writer.write_credentials.call_args.args[1]
        assert token.type == "openai_api_key"
        assert token.credentials == {"api_key": "sk-openai"}
