"""Per-run isolated directory management for concurrent agent_view execution.

Each job gets its own run directory: {base}/{workspace_code}/{agent_view_code}/runs/{job_id}/
Directories are created before execution and cleaned up after completion.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_WORKSPACE_DIR = os.environ.get("AGENTO_WORKSPACE_DIR", "/workspace")


def build_run_dir(workspace_code: str, agent_view_code: str, job_id: int) -> Path:
    """Build the isolated run directory path for a single job execution."""
    return Path(BASE_WORKSPACE_DIR) / workspace_code / agent_view_code / "runs" / str(job_id)


def prepare_run_dir(run_dir: Path) -> None:
    """Create the run directory tree."""
    run_dir.mkdir(parents=True, exist_ok=True)


def cleanup_run_dir(run_dir: Path) -> None:
    """Remove the run directory after job completion."""
    try:
        if run_dir.exists():
            shutil.rmtree(run_dir)
            logger.debug("Cleaned up run dir %s", run_dir)
    except Exception:
        logger.warning("Failed to clean up run dir %s", run_dir, exc_info=True)


def get_current_build_dir(workspace_code: str, agent_view_code: str) -> Path | None:
    """Return the current build directory if the symlink exists and target is valid."""
    current_link = Path(BASE_WORKSPACE_DIR) / workspace_code / agent_view_code / "current"
    if current_link.is_symlink():
        target = current_link.resolve()
        if target.is_dir():
            return target
    return None


def copy_build_to_run_dir(build_dir: Path, run_dir: Path) -> None:
    """Copy pre-built workspace contents into the run directory."""
    for item in build_dir.iterdir():
        dest = run_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
