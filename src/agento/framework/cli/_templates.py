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
