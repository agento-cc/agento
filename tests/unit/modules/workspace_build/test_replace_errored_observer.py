"""Tests for ReplaceErroredTokenCredentialsObserver — replaces stale credentials
in every existing build dir with the next LRU healthy token after a token is
flipped to status='error'."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agento.framework.agent_manager.models import AgentProvider, Token, TokenStatus
from agento.modules.workspace_build.src.observers import (
    ReplaceErroredTokenCredentialsObserver,
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
    build_dir = base / ws / av / "builds" / str(build_id)
    build_dir.mkdir(parents=True)
    current = base / ws / av / "current"
    current.symlink_to(build_dir)
    return build_dir


def _make_event(agent_type: str | None = "codex"):
    event = MagicMock()
    event.agent_type = agent_type
    event.token_id = 6
    event.error_msg = "refresh token already used"
    event.job_id = None
    return event


def _make_token(token_id: int = 2, creds: dict | None = None) -> Token:
    now = datetime.now(UTC).replace(tzinfo=None)
    return Token(
        id=token_id,
        agent_type=AgentProvider.CODEX,
        type="oauth",
        label="mklauza-codex",
        credentials=creds or {"subscription_key": "sk-healthy"},
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


def _patch_db(monkeypatch):
    """Wire DB connection + DatabaseConfig to MagicMocks so the observer can
    exit the ``conn.close()`` finally block without touching a real DB."""
    monkeypatch.setattr(
        "agento.framework.db.get_connection",
        lambda _cfg: MagicMock(),
    )
    monkeypatch.setattr(
        "agento.framework.database_config.DatabaseConfig.from_env",
        classmethod(lambda cls: MagicMock()),
    )


class TestReplaceErroredTokenObserver:
    def test_writes_healthy_token_creds_into_every_current_build(
        self, build_root, monkeypatch,
    ):
        zyga = _make_build(build_root, "default", "zyga")
        mieszko = _make_build(build_root, "default", "mieszko")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )
        _patch_db(monkeypatch)

        healthy = _make_token(token_id=2, creds={"subscription_key": "sk-good"})
        resolver = MagicMock()
        resolver.resolve.return_value = healthy
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda: resolver,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

        called_dirs = {call.args[0] for call in writer.write_credentials.call_args_list}
        assert called_dirs == {zyga, mieszko}
        for call in writer.write_credentials.call_args_list:
            assert call.args[1] is healthy
        # Resolver got the provider derived from the event's agent_type.
        assert resolver.resolve.call_args.args[1] == AgentProvider.CODEX

    def test_noop_when_no_healthy_token(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )
        _patch_db(monkeypatch)

        resolver = MagicMock()
        resolver.resolve.side_effect = RuntimeError(
            "All 1 enabled tokens for provider=codex are unhealthy",
        )
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda: resolver,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

        writer.write_credentials.assert_not_called()

    def test_skips_when_no_agent_type(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event(agent_type=None))

        writer.write_credentials.assert_not_called()

    def test_skips_when_writer_not_registered(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        def _raise(_provider):
            raise KeyError("no writer")

        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            _raise,
        )

        # Must not raise even though no ConfigWriter is registered.
        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

    def test_skips_when_agent_type_unknown_to_enum(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )

        ReplaceErroredTokenCredentialsObserver().execute(
            _make_event(agent_type="bogus_provider"),
        )

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
        _patch_db(monkeypatch)

        resolver = MagicMock()
        resolver.resolve.return_value = _make_token()
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda: resolver,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

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
        _patch_db(monkeypatch)

        resolver = MagicMock()
        resolver.resolve.return_value = _make_token()
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda: resolver,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

        writer.write_credentials.assert_not_called()

    def test_skips_when_replacement_has_no_credentials(self, build_root, monkeypatch):
        _make_build(build_root, "default", "zyga")

        writer = MagicMock()
        monkeypatch.setattr(
            "agento.modules.workspace_build.src.observers.get_config_writer",
            lambda _provider: writer,
        )
        _patch_db(monkeypatch)

        bad = _make_token(creds=None)
        bad.credentials = None
        resolver = MagicMock()
        resolver.resolve.return_value = bad
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda: resolver,
        )

        ReplaceErroredTokenCredentialsObserver().execute(_make_event())

        writer.write_credentials.assert_not_called()
