"""agento toolbox start — run the Node.js toolbox locally."""
from __future__ import annotations

import argparse
import importlib.resources
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ._env import load_project_env
from ._output import log_error, log_info
from ._project import find_project_root


def _find_toolbox_dir() -> Path | None:
    """Find the toolbox directory."""
    # 1. Relative to project root (dev mode / git clone)
    project_root = find_project_root()
    if project_root:
        candidate = project_root / "src" / "agento" / "toolbox"
        if (candidate / "server.js").is_file():
            return candidate

    # 2. Inside installed package (pip/uv install)
    try:
        pkg = importlib.resources.files("agento.toolbox")
        # importlib.resources may return a Traversable, not a real Path
        pkg_path = Path(str(pkg))
        if (pkg_path / "server.js").is_file():
            return pkg_path
    except (TypeError, ModuleNotFoundError):
        pass

    return None


def cmd_toolbox_start(args: argparse.Namespace) -> None:
    """Start the Node.js toolbox locally."""
    # Check Node.js
    if not shutil.which("node"):
        log_error("Node.js not found. Install Node.js to run the toolbox locally.")
        sys.exit(1)

    # Find toolbox
    toolbox_dir = _find_toolbox_dir()
    if toolbox_dir is None:
        log_error("Toolbox directory not found. Run from an agento project or install via pip.")
        sys.exit(1)

    # Install npm deps if needed
    if not (toolbox_dir / "node_modules").is_dir():
        log_info("Installing toolbox dependencies...")
        lockfile = toolbox_dir / "package-lock.json"
        npm_cmd = ["npm", "ci"] if lockfile.is_file() else ["npm", "install"]
        result = subprocess.run(npm_cmd, cwd=str(toolbox_dir))
        if result.returncode != 0:
            log_error("Failed to install toolbox dependencies.")
            sys.exit(result.returncode)

    # Build environment
    project_root = find_project_root()
    env = load_project_env(project_root) if project_root else dict(os.environ)

    # Set module discovery paths
    if project_root:
        env.setdefault("CORE_MODULES_DIR", str(project_root / "src" / "agento" / "modules"))
        env.setdefault("USER_MODULES_DIR", str(project_root / "app" / "code"))

    # Default port
    env.setdefault("PORT", "3001")

    # Validate MySQL connectivity
    host = env.get("CRONDB_HOST") or env.get("CONFIG__DATABASE__MYSQL_HOST")
    if not host:
        log_error(
            "External MySQL required. Set connection params in .env or environment:\n"
            "  CRONDB_HOST, CRONDB_PORT, CRONDB_USER, CRONDB_PASSWORD, CRONDB_DATABASE"
        )
        sys.exit(1)

    port = env.get("PORT", "3001")
    log_info(f"Starting toolbox at http://localhost:{port}")

    try:
        subprocess.run(
            ["node", "server.js"],
            cwd=str(toolbox_dir),
            env=env,
        )
    except KeyboardInterrupt:
        log_info("Toolbox stopped.")
