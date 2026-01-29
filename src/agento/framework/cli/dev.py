"""agento dev bootstrap — set up development environment."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from ._output import log_error, log_info
from ._project import find_project_root


def cmd_dev_bootstrap(args: argparse.Namespace) -> None:
    """Set up the development environment (replaces scripts/bootstrap-dev.sh)."""
    project_root = find_project_root()
    if project_root is None:
        log_error("Not inside an agento project. Run from the repo root.")
        sys.exit(1)

    log_info("Bootstrapping development environment...")

    # Check prerequisites
    errors = []
    if sys.version_info < (3, 11):  # noqa: UP036
        errors.append(f"Python >= 3.11 required (found {sys.version_info.major}.{sys.version_info.minor})")
    if not shutil.which("uv"):
        errors.append("uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/")
    if not shutil.which("node"):
        errors.append("Node.js not found. Install Node.js >= 18.")
    if not shutil.which("npm"):
        errors.append("npm not found.")

    if errors:
        for e in errors:
            log_error(e)
        sys.exit(1)

    # Install Python deps
    log_info("Installing Python dependencies...")
    result = subprocess.run(["uv", "sync", "--group", "dev"], cwd=str(project_root))
    if result.returncode != 0:
        log_error("Failed to install Python dependencies.")
        sys.exit(result.returncode)

    # Install Node.js deps
    toolbox_dir = project_root / "src" / "agento" / "toolbox"
    if toolbox_dir.is_dir():
        log_info("Installing toolbox dependencies...")
        result = subprocess.run(["npm", "install"], cwd=str(toolbox_dir))
        if result.returncode != 0:
            log_error("Failed to install toolbox dependencies.")
            sys.exit(result.returncode)

    log_info("Development setup complete!")
