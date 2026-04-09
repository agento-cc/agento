"""Tests for workspace_build CLI commands."""
from __future__ import annotations

import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

from agento.framework.workspace import AgentView
from agento.modules.workspace_build.src.builder import BuildResult
from agento.modules.workspace_build.src.commands.workspace_build import WorkspaceBuildCommand
from agento.modules.workspace_build.src.commands.workspace_build_status import WorkspaceBuildStatusCommand


def _make_agent_view(**overrides):
    defaults = dict(
        id=1, workspace_id=10, code="dev", label="Developer",
        is_active=True, created_at=datetime.now(), updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return AgentView(**defaults)


class TestWorkspaceBuildCommand:
    def test_properties(self):
        cmd = WorkspaceBuildCommand()
        assert cmd.name == "workspace:build"
        assert cmd.shortcut == "ws:b"
        assert cmd.help

    def test_configure_adds_mutually_exclusive_args(self):
        cmd = WorkspaceBuildCommand()
        parser = argparse.ArgumentParser()
        cmd.configure(parser)
        args = parser.parse_args(["--agent-view", "dev"])
        assert args.agent_view == "dev"
        args = parser.parse_args(["--all"])
        assert args.all is True

    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    @patch("agento.modules.workspace_build.src.builder.execute_build")
    def test_execute_single_agent_view(self, mock_build, mock_get_av, mock_conn, mock_config, capsys):
        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_conn.return_value = MagicMock()
        mock_get_av.return_value = _make_agent_view()
        mock_build.return_value = BuildResult(build_id=1, build_dir="/ws/dev/builds/1", checksum="a" * 64)

        cmd = WorkspaceBuildCommand()
        cmd.execute(argparse.Namespace(agent_view="dev", all=False))

        output = capsys.readouterr().out
        assert "Built" in output
        assert "build 1" in output

    @patch("agento.framework.cli.runtime._load_framework_config")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.workspace.get_agent_view_by_code")
    def test_execute_agent_view_not_found(self, mock_get_av, mock_conn, mock_config, capsys):
        mock_config.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_conn.return_value = MagicMock()
        mock_get_av.return_value = None

        cmd = WorkspaceBuildCommand()
        cmd.execute(argparse.Namespace(agent_view="missing", all=False))

        output = capsys.readouterr().out
        assert "Error" in output


class TestWorkspaceBuildStatusCommand:
    def test_properties(self):
        cmd = WorkspaceBuildStatusCommand()
        assert cmd.name == "workspace:build-status"
        assert cmd.shortcut == "ws:bs"
        assert cmd.help
