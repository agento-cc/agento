"""Module enable/disable state — file-based, Magento app/etc/config.php equivalent.

Stores module status in ``app/etc/modules.json``.
Modules not listed default to enabled (backward compatible).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

from .module_loader import ModuleManifest

logger = logging.getLogger(__name__)

ModuleSource = Literal["local", "pypi", "missing"]

_DOCKER_PATH = Path("/app/etc/modules.json")


def _resolve_path() -> Path:
    """Docker path takes priority, otherwise use <cwd>/app/etc/modules.json.

    Using cwd (not a path derived from ``__file__``) keeps this correct both
    when running from source and when running an installed package via
    ``uv tool install``.
    """
    if _DOCKER_PATH.parent.is_dir():
        return _DOCKER_PATH
    return Path.cwd() / "app" / "etc" / "modules.json"


def read_module_status(path: Path | None = None) -> dict[str, bool]:
    """Read modules.json. Returns empty dict if file doesn't exist."""
    p = path or _resolve_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read %s, treating all modules as enabled", p)
        return {}


def write_module_status(status: dict[str, bool], path: Path | None = None) -> None:
    """Write modules.json atomically. Creates parent directory if needed."""
    p = path or _resolve_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, (json.dumps(status, indent=2) + "\n").encode())
        os.close(fd)
        closed = True
        os.replace(tmp, p)
    except BaseException:
        if not closed:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def is_enabled(name: str, status: dict[str, bool] | None = None) -> bool:
    """Check if module is enabled. Defaults to True if not in file."""
    if status is None:
        status = read_module_status()
    return status.get(name, True)


def set_enabled(name: str, enabled: bool, path: Path | None = None) -> None:
    """Set module enabled state."""
    status = read_module_status(path)
    status[name] = enabled
    write_module_status(status, path)


def filter_enabled(
    manifests: list[ModuleManifest], path: Path | None = None
) -> list[ModuleManifest]:
    """Filter manifests to only enabled modules."""
    status = read_module_status(path)
    return [m for m in manifests if is_enabled(m.name, status)]


def resolve_module_source(
    name: str,
    project_dir: Path,
    venv_path: Path | None = None,
) -> ModuleSource:
    """Determine where a module is sourced from.

    - ``"local"``: ``<project_dir>/app/code/<name>/module.json`` exists.
    - ``"pypi"``: package importable from ``<venv>/lib/python*/site-packages/<name>/``.
    - ``"missing"``: neither.

    The local check wins when both exist (Magento-like override semantics).
    """
    if (project_dir / "app" / "code" / name / "module.json").is_file():
        return "local"

    venv = venv_path or (project_dir / ".venv")
    if venv.is_dir():
        for site_packages in venv.glob("lib/python*/site-packages"):
            if (site_packages / name / "__init__.py").is_file():
                return "pypi"
    return "missing"
