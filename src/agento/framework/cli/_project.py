"""Project root detection and utilities for agento CLI."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ._output import log_error


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start (default: cwd) looking for an agento project root.

    Detection order:
    1. .agento/project.json — created by `agento install`
    2. pyproject.toml with name = "agento" — git clone dev mode
    """
    current = (start or Path.cwd()).resolve()

    for directory in [current, *current.parents]:
        # agento install'd project
        if (directory / ".agento" / "project.json").is_file():
            return directory
        # git clone dev mode
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text()
                if 'name = "agento"' in text or 'name = "agento-core"' in text:
                    return directory
            except OSError:
                continue
    return None


def find_compose_file(project_root: Path) -> Path | None:
    """Find docker-compose file relative to project root.

    Checks (first match wins):
    1. docker/docker-compose.yml (customer install or legacy dev)
    2. docker/docker-compose.dev.yml (dev mode)
    3. docker-compose.yml (init'd project — written by agento install)
    """
    for candidate in [
        project_root / "docker" / "docker-compose.yml",
        project_root / "docker" / "docker-compose.dev.yml",
        project_root / "docker-compose.yml",
    ]:
        if candidate.is_file():
            return candidate
    return None


def resolve_host_ids() -> tuple[int, int]:
    """Detect the current process UID/GID. Refuse running as root.

    The container `agent` user is created at image build time with these IDs
    so bind-mounted host paths are writable by the unprivileged in-container
    user. UID 0 would defeat that model — bake root into the image, then
    every file the container writes is host-root-owned. Refuse instead and
    tell the operator to re-run as the project tree owner.
    """
    uid = os.getuid()
    gid = os.getgid()
    if uid == 0:
        log_error(
            "Refusing to run as root. Re-run as the non-root host user "
            "that owns the project tree — that UID/GID is baked into the "
            "container `agent` user."
        )
        sys.exit(1)
    return uid, gid


def update_dotenv_value(path: Path, key: str, value: str) -> None:
    """Update a single key in a .env file, preserving all other content.

    If the key exists, its value is replaced. If not, the key=value is appended.
    Comments and blank lines are preserved.
    """
    lines = path.read_text().splitlines(keepends=True)
    pattern = re.compile(rf"^{re.escape(key)}=")
    found = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    path.write_text("".join(lines))
