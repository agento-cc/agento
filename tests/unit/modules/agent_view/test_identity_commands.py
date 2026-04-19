"""Tests for agent_view:identity:set-ssh-key / remove-ssh-key / show CLI commands."""
from __future__ import annotations

import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.workspace import AgentView
from agento.modules.agent_view.src.commands.identity_remove_ssh_key import (
    IdentityRemoveSshKeyCommand,
)
from agento.modules.agent_view.src.commands.identity_set_ssh_key import (
    IdentitySetSshKeyCommand,
)
from agento.modules.agent_view.src.commands.identity_show import IdentityShowCommand


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def _make_agent_view(id=1, code="dev_01", workspace_id=10):
    now = datetime(2026, 1, 1)
    return AgentView(
        id=id, workspace_id=workspace_id, code=code, label="Dev",
        is_active=True, created_at=now, updated_at=now,
    )


_PRIVATE_KEY_PEM = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZWQy
NTUxOQAAACAvalidFakeKey0123456789abcdef0123456789abcdef0123
-----END OPENSSH PRIVATE KEY-----
"""


class TestIdentitySetSshKeyCommand:
    def test_properties(self):
        cmd = IdentitySetSshKeyCommand()
        assert cmd.name == "agent_view:identity:set-ssh-key"
        assert "SSH" in cmd.help or "ssh" in cmd.help.lower()

    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    @patch("agento.modules.agent_view.src.commands.identity_set_ssh_key.scoped_config_set")
    def test_stores_private_and_public_keys(
        self, mock_set, mock_av, mock_config, mock_get_conn, tmp_path,
    ):
        mock_config.return_value = ({}, None, None)
        mock_get_conn.return_value = _mock_conn()[0]
        mock_av.return_value = _make_agent_view(id=42, code="dev_01")

        private_file = tmp_path / "id_rsa"
        private_file.write_text(_PRIVATE_KEY_PEM)
        public_file = tmp_path / "id_rsa.pub"
        public_file.write_text("ssh-ed25519 AAAA user@host\n")

        args = argparse.Namespace(
            agent_view_code="dev_01",
            private_key_path=str(private_file),
            public_key_path=None,
            scope=None,
            scope_id=None,
        )
        IdentitySetSshKeyCommand().execute(args)

        # private key and public key both written via scoped_config_set
        assert mock_set.call_count == 2
        private_call = mock_set.call_args_list[0]
        assert private_call.args[1] == "agent_view/identity/ssh_private_key"
        assert private_call.args[2] == _PRIVATE_KEY_PEM
        assert private_call.kwargs["encrypted"] is True
        assert private_call.kwargs["scope"] == "agent_view"
        assert private_call.kwargs["scope_id"] == 42

        public_call = mock_set.call_args_list[1]
        assert public_call.args[1] == "agent_view/identity/ssh_public_key"
        assert public_call.kwargs.get("encrypted", False) is False

    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_missing_private_key_file_exits(
        self, mock_config, mock_get_conn, tmp_path,
    ):
        mock_config.return_value = ({}, None, None)
        args = argparse.Namespace(
            agent_view_code="dev_01",
            private_key_path=str(tmp_path / "missing"),
            public_key_path=None,
            scope=None,
            scope_id=None,
        )
        with pytest.raises(SystemExit):
            IdentitySetSshKeyCommand().execute(args)

    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_rejects_non_pem_file(self, mock_config, mock_get_conn, tmp_path):
        mock_config.return_value = ({}, None, None)
        bad = tmp_path / "not_a_key"
        bad.write_text("hello world")
        args = argparse.Namespace(
            agent_view_code="dev_01",
            private_key_path=str(bad),
            public_key_path=None,
            scope=None,
            scope_id=None,
        )
        with pytest.raises(SystemExit):
            IdentitySetSshKeyCommand().execute(args)


class TestIdentityRemoveSshKeyCommand:
    def test_properties(self):
        cmd = IdentityRemoveSshKeyCommand()
        assert cmd.name == "agent_view:identity:remove-ssh-key"

    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    def test_deletes_identity_rows(
        self, mock_av, mock_config, mock_get_conn,
    ):
        mock_config.return_value = ({}, None, None)
        conn, cursor = _mock_conn()
        cursor.rowcount = 2
        mock_get_conn.return_value = conn
        mock_av.return_value = _make_agent_view(id=42)

        args = argparse.Namespace(
            agent_view_code="dev_01", scope=None, scope_id=None,
        )
        IdentityRemoveSshKeyCommand().execute(args)

        delete_sql = cursor.execute.call_args[0][0]
        assert "DELETE FROM core_config_data" in delete_sql
        params = cursor.execute.call_args[0][1]
        assert params[0] == "agent_view"
        assert params[1] == 42
        assert "agent_view/identity/ssh_private_key" in params


class TestIdentityShowCommand:
    def test_properties(self):
        cmd = IdentityShowCommand()
        assert cmd.name == "agent_view:identity:show"

    @patch("agento.modules.agent_view.src.commands.identity_show.build_scoped_overrides")
    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    def test_prints_no_identity_message_when_absent(
        self, mock_av, mock_config, mock_get_conn, mock_overrides, capsys,
    ):
        mock_config.return_value = ({}, None, None)
        mock_get_conn.return_value = _mock_conn()[0]
        mock_av.return_value = _make_agent_view(code="dev_01")
        mock_overrides.return_value = {}

        args = argparse.Namespace(agent_view_code="dev_01")
        IdentityShowCommand().execute(args)

        output = capsys.readouterr().out
        assert "No SSH identity stored" in output

    @patch("agento.framework.encryptor.get_encryptor")
    @patch("agento.modules.agent_view.src.commands.identity_show.build_scoped_overrides")
    @patch("agento.framework.db.get_connection_or_exit")
    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    def test_shows_fingerprint_and_pub(
        self, mock_av, mock_config, mock_get_conn, mock_overrides, mock_enc, capsys,
    ):
        mock_config.return_value = ({}, None, None)
        mock_get_conn.return_value = _mock_conn()[0]
        mock_av.return_value = _make_agent_view(id=7, code="dev_01")
        mock_overrides.return_value = {
            "agent_view/identity/ssh_private_key": ("encrypted-blob", True),
            "agent_view/identity/ssh_public_key": ("ssh-ed25519 AAAA user@host", False),
        }
        fake_enc = MagicMock()
        fake_enc.decrypt.return_value = _PRIVATE_KEY_PEM
        mock_enc.return_value = fake_enc

        args = argparse.Namespace(agent_view_code="dev_01")
        IdentityShowCommand().execute(args)

        output = capsys.readouterr().out
        assert "dev_01" in output
        assert "private key: stored" in output
        assert "ssh-ed25519" in output
        # Never dumps the private key text
        assert "BEGIN OPENSSH PRIVATE KEY" not in output
