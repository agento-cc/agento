"""Shared template loading utilities."""
from __future__ import annotations

import importlib.resources
from pathlib import Path


class TemplateNotFoundError(Exception):
    pass


def get_template(name: str) -> str:
    """Read a template file from the templates directory."""
    # Try importlib.resources first (pip-installed)
    try:
        templates = importlib.resources.files("agento.framework.cli") / "templates"
        return (templates / name).read_text()
    except (TypeError, FileNotFoundError, ModuleNotFoundError):
        pass

    # Fall back to relative path (dev mode)
    template_dir = Path(__file__).parent / "templates"
    template_path = template_dir / name
    if template_path.is_file():
        return template_path.read_text()

    raise TemplateNotFoundError(name)


def get_package_version() -> str:
    """Get installed agento-core version. Falls back to 'latest' for dev."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("agento-core")
    except PackageNotFoundError:
        return "latest"


def extract_sql_files(target_dir: Path) -> None:
    """Copy consolidated init schema for docker-entrypoint-initdb.d.

    Only the single ``000_init.sql`` file is extracted (from the ``init/``
    sub-package).  Individual migration files stay in the ``sql/`` package
    for ``setup:upgrade`` to apply incrementally on existing databases.
    """
    init_pkg = importlib.resources.files("agento.framework.sql.init")
    target_dir.mkdir(parents=True, exist_ok=True)
    for resource in init_pkg.iterdir():
        if resource.name.endswith(".sql"):
            (target_dir / resource.name).write_text(resource.read_text())
