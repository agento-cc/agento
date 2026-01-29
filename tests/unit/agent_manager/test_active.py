from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agento.framework.agent_manager.active import (
    read_credentials,
    resolve_active_token,
    update_active_token,
)
from agento.framework.agent_manager.models import AgentProvider

from .conftest import make_token


class TestResolveActiveToken:
    def test_returns_none_when_no_symlink(self, agent_config):
        result = resolve_active_token(agent_config, AgentProvider.CLAUDE)

        assert result is None

    def test_returns_target_path(self, agent_config):
        # Create a credential file and symlink
        cred_file = Path(agent_config.tokens_dir) / "claude_1.json"
        cred_file.write_text('{"subscription_key": "sk-test"}')
        link = Path(agent_config.active_dir) / "claude"
        link.symlink_to(cred_file)

        result = resolve_active_token(agent_config, AgentProvider.CLAUDE)

        assert result == str(cred_file)

    def test_returns_none_when_target_missing(self, agent_config):
        # Symlink pointing to a non-existent file
        link = Path(agent_config.active_dir) / "claude"
        link.symlink_to("/nonexistent/file.json")

        result = resolve_active_token(agent_config, AgentProvider.CLAUDE)

        assert result is None


class TestUpdateActiveToken:
    def test_creates_new_symlink(self, agent_config):
        cred_file = Path(agent_config.tokens_dir) / "claude_1.json"
        cred_file.write_text('{"subscription_key": "sk-test"}')
        token = make_token(credentials_path=str(cred_file))

        update_active_token(agent_config, AgentProvider.CLAUDE, token)

        link = Path(agent_config.active_dir) / "claude"
        assert link.is_symlink()
        assert link.resolve() == cred_file.resolve()

    def test_replaces_existing_symlink(self, agent_config):
        # Create two credential files
        cred1 = Path(agent_config.tokens_dir) / "claude_1.json"
        cred1.write_text('{"subscription_key": "sk-1"}')
        cred2 = Path(agent_config.tokens_dir) / "claude_2.json"
        cred2.write_text('{"subscription_key": "sk-2"}')

        token1 = make_token(id=1, credentials_path=str(cred1))
        token2 = make_token(id=2, credentials_path=str(cred2))

        # Set first, then switch to second
        update_active_token(agent_config, AgentProvider.CLAUDE, token1)
        update_active_token(agent_config, AgentProvider.CLAUDE, token2)

        link = Path(agent_config.active_dir) / "claude"
        assert link.resolve() == cred2.resolve()

    def test_atomic_replace_preserves_link(self, agent_config):
        """After update, the symlink path still exists (not broken by rename)."""
        cred_file = Path(agent_config.tokens_dir) / "codex_1.json"
        cred_file.write_text('{"subscription_key": "sk-codex"}')
        token = make_token(agent_type=AgentProvider.CODEX, credentials_path=str(cred_file))

        update_active_token(agent_config, AgentProvider.CODEX, token)

        link = Path(agent_config.active_dir) / "codex"
        assert link.exists()
        assert os.readlink(str(link)) == str(cred_file)


class TestReadCredentials:
    def test_reads_json(self, tmp_path):
        cred_file = tmp_path / "creds.json"
        cred_file.write_text(json.dumps({"subscription_key": "sk-test", "org": "my-org"}))

        result = read_credentials(str(cred_file))

        assert result == {"subscription_key": "sk-test", "org": "my-org"}

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            read_credentials("/nonexistent/file.json")

    def test_raises_on_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all")

        with pytest.raises(json.JSONDecodeError):
            read_credentials(str(bad_file))
