"""Tests for agent_view worker subprocess management."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.agent_view_worker import (
    WorkerHandle,
    build_working_dir,
    prepare_working_dir,
    start_worker,
    stop_worker,
)
from agento.framework.workspace import AgentView, Workspace


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 0, 0)


@pytest.fixture
def workspace(now):
    return Workspace(
        id=1, code="main", label="Main", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture
def agent_view(now):
    return AgentView(
        id=10, workspace_id=1, code="alpha", label="Agent Alpha",
        is_active=True, created_at=now, updated_at=now,
    )


class TestBuildWorkingDir:
    def test_builds_correct_path(self, workspace, agent_view):
        path = build_working_dir(workspace, agent_view)
        assert path == Path("/workspace/main/alpha")

    def test_uses_workspace_and_view_codes(self, now):
        ws = Workspace(id=2, code="dev", label="Dev", is_active=True, created_at=now, updated_at=now)
        av = AgentView(id=20, workspace_id=2, code="beta", label="Beta", is_active=True, created_at=now, updated_at=now)
        path = build_working_dir(ws, av)
        assert path == Path("/workspace/dev/beta")


class TestPrepareWorkingDir:
    def test_creates_directory(self, tmp_path):
        wd = tmp_path / "deep" / "nested" / "dir"
        prepare_working_dir(wd)
        assert wd.is_dir()

    def test_idempotent(self, tmp_path):
        wd = tmp_path / "ws"
        prepare_working_dir(wd)
        prepare_working_dir(wd)
        assert wd.is_dir()


class TestStartWorker:
    @patch("agento.framework.agent_view_worker.subprocess.Popen")
    def test_starts_subprocess(self, mock_popen, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        wd = tmp_path / "workspace" / "main" / "alpha"
        wd.mkdir(parents=True)

        handle = start_worker(agent_view, workspace, wd)

        assert handle.agent_view == agent_view
        assert handle.workspace == workspace
        assert handle.working_dir == wd
        assert handle.process == mock_process

        # Verify subprocess.Popen called with correct args
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0] == sys.executable
        assert "-m" in cmd
        assert "agento.framework.cli" in cmd
        assert "consumer" in cmd
        assert "--agent-view-id" in cmd
        assert "10" in cmd

    @patch("agento.framework.agent_view_worker.subprocess.Popen")
    def test_sets_env_vars(self, mock_popen, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        wd = tmp_path / "workspace" / "main" / "alpha"
        wd.mkdir(parents=True)

        start_worker(agent_view, workspace, wd)

        call_kwargs = mock_popen.call_args[1]
        env = call_kwargs["env"]
        assert env["AGENTO_AGENT_VIEW_ID"] == "10"
        assert env["AGENTO_AGENT_VIEW_CODE"] == "alpha"
        assert env["AGENTO_WORKSPACE_ID"] == "1"
        assert env["AGENTO_WORKSPACE_CODE"] == "main"

    @patch("agento.framework.agent_view_worker.subprocess.Popen")
    def test_sets_cwd(self, mock_popen, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        wd = tmp_path / "workspace" / "main" / "alpha"
        wd.mkdir(parents=True)

        start_worker(agent_view, workspace, wd)

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["cwd"] == str(wd)


class TestStopWorker:
    def test_stops_running_process(self, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # process still running
        mock_process.returncode = 0
        mock_process.pid = 12345
        mock_process.wait.return_value = None

        handle = WorkerHandle(
            agent_view=agent_view,
            workspace=workspace,
            working_dir=tmp_path,
            process=mock_process,
        )

        rc = stop_worker(handle, timeout=5)
        mock_process.send_signal.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=5)
        assert rc == 0

    def test_returns_none_for_no_process(self, workspace, agent_view, tmp_path):
        handle = WorkerHandle(
            agent_view=agent_view,
            workspace=workspace,
            working_dir=tmp_path,
            process=None,
        )
        assert stop_worker(handle) is None

    def test_returns_code_if_already_exited(self, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # already exited
        mock_process.returncode = 0

        handle = WorkerHandle(
            agent_view=agent_view,
            workspace=workspace,
            working_dir=tmp_path,
            process=mock_process,
        )
        rc = stop_worker(handle)
        assert rc == 0
        mock_process.send_signal.assert_not_called()

    def test_sigkill_on_timeout(self, workspace, agent_view, tmp_path):
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        mock_process.returncode = -9
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 5),
            None,
        ]

        handle = WorkerHandle(
            agent_view=agent_view,
            workspace=workspace,
            working_dir=tmp_path,
            process=mock_process,
        )

        rc = stop_worker(handle, timeout=5)
        mock_process.kill.assert_called_once()
        assert rc == -9
