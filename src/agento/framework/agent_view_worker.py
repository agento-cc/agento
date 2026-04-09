"""Agent view worker — subprocess-based parallel execution per agent_view.

.. deprecated:: Phase 9.5
    Replaced by the consumer's built-in worker pool with per-run directory isolation.
    Use ``ConsumerConfig.max_workers`` to configure concurrency instead.

Each agent_view gets:
  - Its own working directory: /workspace/{workspace_code}/{agent_view_code}/
  - Config files generated from scoped config (agent_view -> workspace -> global)
  - A dedicated subprocess that runs the consumer loop for that agent_view's jobs
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from .workspace import AgentView, Workspace
from .workspace_paths import BASE_WORKSPACE_DIR

logger = logging.getLogger(__name__)


@dataclass
class WorkerHandle:
    agent_view: AgentView
    workspace: Workspace
    working_dir: Path
    process: subprocess.Popen | None = None


def build_working_dir(workspace: Workspace, agent_view: AgentView) -> Path:
    """Build the isolated working directory path for an agent_view."""
    return Path(BASE_WORKSPACE_DIR) / workspace.code / agent_view.code


def prepare_working_dir(working_dir: Path) -> None:
    """Ensure the working directory exists."""
    working_dir.mkdir(parents=True, exist_ok=True)


def start_worker(
    agent_view: AgentView,
    workspace: Workspace,
    working_dir: Path,
) -> WorkerHandle:
    """Start a subprocess worker for an agent_view.

    .. deprecated:: Phase 9.5
        Use the consumer's built-in worker pool instead.
    """
    warnings.warn(
        "start_worker() is deprecated. Use ConsumerConfig.max_workers for concurrency.",
        DeprecationWarning,
        stacklevel=2,
    )
    env = {
        **os.environ,
        "AGENTO_AGENT_VIEW_ID": str(agent_view.id),
        "AGENTO_AGENT_VIEW_CODE": agent_view.code,
        "AGENTO_WORKSPACE_ID": str(workspace.id),
        "AGENTO_WORKSPACE_CODE": workspace.code,
    }

    cmd = [
        sys.executable, "-m", "agento.framework.cli",
        "consumer",
        "--agent-view-id", str(agent_view.id),
    ]

    process = subprocess.Popen(
        cmd,
        cwd=str(working_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    logger.info(
        "Started worker pid=%d for agent_view=%s (workspace=%s) in %s",
        process.pid, agent_view.code, workspace.code, working_dir,
    )

    return WorkerHandle(
        agent_view=agent_view,
        workspace=workspace,
        working_dir=working_dir,
        process=process,
    )


def stop_worker(handle: WorkerHandle, timeout: int = 30) -> int | None:
    """Stop a worker subprocess gracefully (SIGTERM), then force (SIGKILL)."""
    if handle.process is None or handle.process.poll() is not None:
        return handle.process.returncode if handle.process else None

    import signal

    handle.process.send_signal(signal.SIGTERM)
    try:
        handle.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Worker pid=%d for agent_view=%s did not stop in %ds, sending SIGKILL",
            handle.process.pid, handle.agent_view.code, timeout,
        )
        handle.process.kill()
        handle.process.wait(timeout=5)

    rc = handle.process.returncode
    logger.info(
        "Worker pid=%d for agent_view=%s exited with code %s",
        handle.process.pid, handle.agent_view.code, rc,
    )
    return rc
