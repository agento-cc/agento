"""Tests for state dir + SSH materialization + persistent-path symlinks + retention GC."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agento.framework.agent_manager.models import AgentProvider, Token
from agento.modules.workspace_build.src.builder import (
    ensure_state_dir,
    gc_old_builds,
    link_persistent_paths,
    materialize_agent_credentials,
    materialize_ssh_identity,
)


@pytest.fixture
def workspace_base(tmp_path, monkeypatch):
    base = tmp_path / "workspace" / "build"
    base.mkdir(parents=True)
    monkeypatch.setattr(
        "agento.modules.workspace_build.src.builder.BUILD_DIR", str(base),
    )
    return base


class _FakeEncryptor:
    def encrypt(self, plaintext: str) -> str:
        return f"aes256:iv:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.split(":", 2)[-1]


@pytest.fixture
def fake_encryptor(monkeypatch):
    from agento.framework import encryptor as enc
    monkeypatch.setattr(enc, "_instance", _FakeEncryptor())
    yield


class TestEnsureStateDir:
    def test_creates_state_root_and_subpaths(self, workspace_base):
        result = ensure_state_dir("it", "dev_01", [".claude/projects", ".codex/sessions"])
        expected = workspace_base / "it" / "dev_01" / "state"
        assert result == expected
        assert expected.is_dir()
        assert (expected / ".claude" / "projects").is_dir()
        assert (expected / ".codex" / "sessions").is_dir()

    def test_idempotent_on_second_call(self, workspace_base):
        ensure_state_dir("it", "dev_01", [".claude/projects"])
        # Drop a marker so we can check it survives a re-run
        marker = workspace_base / "it" / "dev_01" / "state" / ".claude" / "projects" / "preserved.jsonl"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("session-data")

        ensure_state_dir("it", "dev_01", [".claude/projects"])

        assert marker.is_file()
        assert marker.read_text() == "session-data"


class TestMaterializeSshIdentity:
    def test_writes_private_key_with_600_perms(self, tmp_path, fake_encryptor):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        overrides = {
            "agent_view/identity/ssh_private_key": ("aes256:iv:-----BEGIN FAKE KEY-----", True),
        }

        materialize_ssh_identity(build_dir, overrides)

        key_path = build_dir / ".ssh" / "id_rsa"
        assert key_path.is_file()
        assert key_path.read_text() == "-----BEGIN FAKE KEY-----\n"
        assert (key_path.stat().st_mode & 0o777) == 0o600
        assert (build_dir / ".ssh").stat().st_mode & 0o777 == 0o700

    def test_writes_public_key_plain(self, tmp_path, fake_encryptor):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        overrides = {
            "agent_view/identity/ssh_public_key": ("ssh-ed25519 AAAA host", False),
        }

        materialize_ssh_identity(build_dir, overrides)

        pub_path = build_dir / ".ssh" / "id_rsa.pub"
        assert pub_path.is_file()
        assert pub_path.read_text() == "ssh-ed25519 AAAA host"

    def test_writes_ssh_config_and_known_hosts(self, tmp_path, fake_encryptor):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        overrides = {
            "agent_view/identity/ssh_config": ("Host git\n  IdentityFile ~/.ssh/id_rsa\n", False),
            "agent_view/identity/ssh_known_hosts": ("github.com ssh-ed25519 AAAA\n", False),
        }

        materialize_ssh_identity(build_dir, overrides)

        config_path = build_dir / ".ssh" / "config"
        known = build_dir / ".ssh" / "known_hosts"
        assert "IdentityFile" in config_path.read_text()
        assert (config_path.stat().st_mode & 0o777) == 0o600
        assert "github.com" in known.read_text()

    def test_does_nothing_when_no_overrides(self, tmp_path, fake_encryptor):
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        materialize_ssh_identity(build_dir, {})

        assert not (build_dir / ".ssh").exists()


class TestLinkPersistentPaths:
    def test_creates_relative_symlinks(self, tmp_path):
        build_dir = tmp_path / "build"
        state_dir = tmp_path / "state"
        build_dir.mkdir()
        state_dir.mkdir()
        (state_dir / ".claude" / "projects").mkdir(parents=True)

        link_persistent_paths(build_dir, state_dir, [".claude/projects"])

        link = build_dir / ".claude" / "projects"
        assert link.is_symlink()
        assert link.resolve() == (state_dir / ".claude" / "projects").resolve()

    def test_replaces_existing_file(self, tmp_path):
        build_dir = tmp_path / "build"
        state_dir = tmp_path / "state"
        build_dir.mkdir()
        state_dir.mkdir()
        (state_dir / ".claude" / "projects").mkdir(parents=True)
        # Pre-existing file where symlink should go
        existing_file = build_dir / ".claude" / "projects"
        existing_file.parent.mkdir(parents=True, exist_ok=True)
        existing_file.write_text("old content")

        link_persistent_paths(build_dir, state_dir, [".claude/projects"])

        assert existing_file.is_symlink()

    def test_replaces_existing_directory(self, tmp_path):
        build_dir = tmp_path / "build"
        state_dir = tmp_path / "state"
        build_dir.mkdir()
        state_dir.mkdir()
        (state_dir / ".codex" / "sessions").mkdir(parents=True)
        (build_dir / ".codex" / "sessions").mkdir(parents=True)
        (build_dir / ".codex" / "sessions" / "stale.file").write_text("x")

        link_persistent_paths(build_dir, state_dir, [".codex/sessions"])

        assert (build_dir / ".codex" / "sessions").is_symlink()


class TestGcOldBuilds:
    def test_keeps_latest_n(self, tmp_path):
        builds = tmp_path / "builds"
        builds.mkdir()
        for i in range(1, 13):
            (builds / str(i)).mkdir()

        removed = gc_old_builds(builds, current_build_id=12, max_builds=10)

        assert sorted(removed) == [1, 2]
        assert not (builds / "1").exists()
        assert not (builds / "2").exists()
        assert (builds / "3").exists()
        assert (builds / "12").exists()

    def test_keeps_current_even_if_older_than_n(self, tmp_path):
        builds = tmp_path / "builds"
        builds.mkdir()
        for i in [1, 2, 3, 4, 5]:
            (builds / str(i)).mkdir()

        # Current is 2, keep max 2 → should keep 5, 4, plus 2 (current)
        removed = gc_old_builds(builds, current_build_id=2, max_builds=2)

        assert 2 not in removed
        assert (builds / "2").exists()
        assert (builds / "5").exists()
        assert (builds / "4").exists()
        assert 3 in removed
        assert 1 in removed

    def test_no_op_when_below_threshold(self, tmp_path):
        builds = tmp_path / "builds"
        builds.mkdir()
        for i in [1, 2, 3]:
            (builds / str(i)).mkdir()

        removed = gc_old_builds(builds, current_build_id=3, max_builds=10)

        assert removed == []
        for i in [1, 2, 3]:
            assert (builds / str(i)).exists()

    def test_ignores_non_numeric_entries(self, tmp_path):
        builds = tmp_path / "builds"
        builds.mkdir()
        (builds / "current").symlink_to(tmp_path)
        (builds / "1").mkdir()
        (builds / "2").mkdir()

        gc_old_builds(builds, current_build_id=2, max_builds=1)

        # Symlink 'current' is ignored (non-numeric name)
        assert (builds / "current").exists() or (builds / "current").is_symlink()


def _token(agent_type, credentials):
    now = datetime.now(UTC)
    return Token(
        id=1, agent_type=agent_type, label="t", credentials=credentials,
        model=None, is_primary=True, token_limit=0, enabled=True,
        created_at=now, updated_at=now,
    )


class TestMaterializeAgentCredentials:
    def test_delegates_per_provider_to_config_writer(self, tmp_path, monkeypatch):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        claude_writer = MagicMock()
        codex_writer = MagicMock()

        monkeypatch.setattr(
            "agento.framework.config_writer._CONFIG_WRITERS",
            {AgentProvider.CLAUDE: claude_writer, AgentProvider.CODEX: codex_writer},
        )

        resolver = MagicMock()
        def fake_resolve(conn, provider):
            if provider == AgentProvider.CLAUDE:
                return _token(AgentProvider.CLAUDE, {"subscription_key": "claude-tok"})
            return _token(AgentProvider.CODEX, {"raw_auth": {"x": 1}})
        resolver.resolve.side_effect = fake_resolve
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda *a, **kw: resolver,
        )

        materialize_agent_credentials(conn=MagicMock(), build_dir=build_dir)

        claude_writer.write_credentials.assert_called_once_with(
            build_dir, {"subscription_key": "claude-tok"},
        )
        codex_writer.write_credentials.assert_called_once_with(
            build_dir, {"raw_auth": {"x": 1}},
        )

    def test_skips_provider_without_enabled_token(self, tmp_path, monkeypatch):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        claude_writer = MagicMock()

        monkeypatch.setattr(
            "agento.framework.config_writer._CONFIG_WRITERS",
            {AgentProvider.CLAUDE: claude_writer},
        )

        resolver = MagicMock()
        resolver.resolve.side_effect = RuntimeError("no enabled tokens")
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda *a, **kw: resolver,
        )

        materialize_agent_credentials(conn=MagicMock(), build_dir=build_dir)

        claude_writer.write_credentials.assert_not_called()

    def test_swallows_write_errors(self, tmp_path, monkeypatch, caplog):
        import logging

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        claude_writer = MagicMock()
        claude_writer.write_credentials.side_effect = RuntimeError("boom")

        monkeypatch.setattr(
            "agento.framework.config_writer._CONFIG_WRITERS",
            {AgentProvider.CLAUDE: claude_writer},
        )
        resolver = MagicMock()
        resolver.resolve.return_value = _token(AgentProvider.CLAUDE, {"subscription_key": "x"})
        monkeypatch.setattr(
            "agento.framework.agent_manager.token_resolver.TokenResolver",
            lambda *a, **kw: resolver,
        )

        with caplog.at_level(logging.WARNING, logger="agento.modules.workspace_build.src.builder"):
            materialize_agent_credentials(conn=MagicMock(), build_dir=build_dir)

        assert "failed to write credentials" in caplog.text
