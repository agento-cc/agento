"""Tests for agent_view:identity:show CLI command."""
from __future__ import annotations

import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

from agento.framework.workspace import AgentView
from agento.modules.agent_view.src.commands.identity_show import IdentityShowCommand

_PRIVATE_KEY_PEM = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZWQy
NTUxOQAAACAvalidFakeKey0123456789abcdef0123456789abcdef0123
-----END OPENSSH PRIVATE KEY-----
"""


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
