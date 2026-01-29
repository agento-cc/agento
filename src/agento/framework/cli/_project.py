"""Project root detection for agento CLI."""
from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start (default: cwd) looking for an agento project root.

    Detection order:
    1. .agento/project.json — created by `agento init`
    2. pyproject.toml with name = "agento" — git clone dev mode
    """
    current = (start or Path.cwd()).resolve()

    for directory in [current, *current.parents]:
        # agento init'd project
        if (directory / ".agento" / "project.json").is_file():
            return directory
        # git clone dev mode
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text()
                if 'name = "agento"' in text:
                    return directory
            except OSError:
                continue
    return None


def find_compose_file(project_root: Path) -> Path | None:
    """Find docker-compose.yml relative to project root.

    Checks:
    1. docker/docker-compose.yml (git clone / dev mode)
    2. docker-compose.yml (init'd project)
    """
    for candidate in [
        project_root / "docker" / "docker-compose.yml",
        project_root / "docker-compose.yml",
    ]:
        if candidate.is_file():
            return candidate
    return None
