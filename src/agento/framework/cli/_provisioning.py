"""Provisioning helpers for `agento install` / `agento upgrade`.

Materializes the in-package Docker build context into the project directory,
generates ``docker-compose.yml`` from the bundled template (substituting
extension mounts based on enabled PyPI modules), and writes/bumps the
project-level ``pyproject.toml``.

This is the Magento-like analogue of Composer's behaviour: the project owns
``pyproject.toml`` + ``uv.lock`` (composer.json + composer.lock equivalents),
the CLI provides the build context. Docker images are built locally — no
GHCR pulls.
"""
from __future__ import annotations

import importlib.resources as ires
import re
import shutil
from pathlib import Path

from ..module_status import read_module_status, resolve_module_source
from ._templates import get_package_version, get_template

_AGENTO_REQUIRES_PYTHON = ">=3.12"


def write_project_pyproject(
    project_dir: Path,
    project_name: str,
    agento_version: str,
) -> None:
    """Write ``<project>/pyproject.toml`` pinned to a specific agento-core version.

    Magento composer.json equivalent. Pin uses ``==`` for deterministic builds.
    """
    content = (
        "[project]\n"
        f'name = "{project_name}"\n'
        'version = "0.1.0"\n'
        f'requires-python = "{_AGENTO_REQUIRES_PYTHON}"\n'
        f'dependencies = ["agento-core=={agento_version}"]\n'
    )
    (project_dir / "pyproject.toml").write_text(content)


def bump_agento_version(pyproject: Path, new_version: str) -> None:
    """Update the ``agento-core==X.Y.Z`` pin in a project's pyproject.toml."""
    text = pyproject.read_text()
    text = re.sub(
        r'agento-core\s*==\s*[^"\'\s,\]]+',
        f"agento-core=={new_version}",
        text,
    )
    pyproject.write_text(text)


def detect_python_version(venv: Path) -> str:
    """Return the venv's Python version as ``major.minor`` (e.g. ``"3.12"``).

    Reads ``pyvenv.cfg`` from the venv root. Falls back to ``"3.12"`` on
    parse failure or missing file — the cron Docker image is pinned to 3.12,
    so that's the safe default that keeps mount paths consistent.
    """
    cfg = venv / "pyvenv.cfg"
    if cfg.is_file():
        for line in cfg.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("version_info") or stripped.startswith("version "):
                _, _, value = stripped.partition("=")
                parts = value.strip().split(".")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return f"{parts[0]}.{parts[1]}"
    return "3.12"


def enumerate_enabled_extensions(project_dir: Path) -> list[str]:
    """Enabled PyPI extensions to mount into containers.

    Returns module names from ``app/etc/modules.json`` where:
    - the entry is enabled (``True``),
    - the module resolves to source ``"pypi"`` (importable from ``.venv``),
    - and is *not* a local module (``app/code/<name>/`` takes precedence).

    Local modules are already mounted through ``app/code/`` and don't need
    per-extension mounts.
    """
    status_path = project_dir / "app" / "etc" / "modules.json"
    status = read_module_status(status_path)
    venv = project_dir / ".venv"
    return sorted(
        name
        for name, enabled in status.items()
        if enabled and resolve_module_source(name, project_dir, venv) == "pypi"
    )


def _copy_tree(src, dst: Path) -> None:
    """Copy a importlib.resources Traversable tree to ``dst`` recursively."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _copy_tree(entry, target)
        else:
            with ires.as_file(entry) as f:
                shutil.copy2(f, target)


def materialize_docker_context(
    project_dir: Path,
    *,
    force: bool = False,
) -> None:
    """Copy the in-package Docker build context to ``<project>/.agento/docker/``.

    Idempotent: stamps ``.agento/docker/version`` with the current agento-core
    version. Skips re-copy when stamp matches and ``force`` is not set.

    The cron build context additionally needs ``pyproject.toml`` + ``uv.lock``
    from the project (so ``uv sync --frozen`` inside the image produces deps
    matching the host venv). The toolbox build context needs
    ``package.json`` + ``package-lock.json`` from the agento.toolbox package.
    """
    target = project_dir / ".agento" / "docker"
    stamp = target / "version"
    current = get_package_version()

    if not force and stamp.is_file() and stamp.read_text().strip() == current:
        return

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    ctx = ires.files("agento.framework.docker")
    _copy_tree(ctx / "sandbox", target / "sandbox")
    _copy_tree(ctx / "cron", target / "cron")
    _copy_tree(ctx / "toolbox", target / "toolbox")

    # Cron context needs the project's lockfile + pyproject for `uv sync`
    # (deps only — agento itself comes from the bind-mounted host venv).
    project_pyproject = project_dir / "pyproject.toml"
    project_lock = project_dir / "uv.lock"
    if project_pyproject.is_file():
        shutil.copy2(project_pyproject, target / "cron" / "pyproject.toml")
    if project_lock.is_file():
        shutil.copy2(project_lock, target / "cron" / "uv.lock")

    # Toolbox context needs npm manifests bundled with the wheel.
    # Wheel build force-includes them under agento.framework.docker.toolbox/,
    # so `_copy_tree(ctx / "toolbox", ...)` already brought them in for
    # installed packages. For source-tree dev runs, fall back to the toolbox
    # package directly.
    toolbox_target = target / "toolbox"
    for name in ("package.json", "package-lock.json"):
        if not (toolbox_target / name).is_file():
            try:
                src = ires.files("agento.toolbox") / name
                with ires.as_file(src) as p:
                    if p.is_file():
                        shutil.copy2(p, toolbox_target / name)
            except (FileNotFoundError, ModuleNotFoundError):
                pass

    stamp.write_text(current + "\n")


def render_compose(
    template: str,
    *,
    python_version: str,
    extensions: list[str],
) -> str:
    """Substitute placeholders in the docker-compose template.

    Template placeholders:
    - ``{{ python_version }}`` — replaced with ``"3.12"`` etc.
    - line ``      # {{ extension_mounts_sandbox }}`` — replaced with mount
      lines for each enabled PyPI extension (or removed when none).
    - line ``      # {{ extension_mounts_cron }}`` — same, for the cron service.
    """
    def mount_block(target_path: str) -> str:
        if not extensions:
            return ""
        lines = [
            f"      - ../.venv/lib/python{python_version}/site-packages/{ext}:{target_path}/{ext}:ro"
            for ext in extensions
        ]
        return "\n".join(lines) + "\n"

    rendered = template.replace(
        "      # {{ extension_mounts_sandbox }}\n",
        mount_block("/opt/agento-src"),
    )
    rendered = rendered.replace(
        "      # {{ extension_mounts_cron }}\n",
        mount_block("/opt/agento-src"),
    )
    rendered = rendered.replace("{{ python_version }}", python_version)
    return rendered


def regenerate_compose(project_dir: Path) -> None:
    """Render and write ``<project>/docker/docker-compose.yml`` from template.

    Reads enabled extensions from ``app/etc/modules.json``, detects the
    project venv's Python version, substitutes mount lines, writes the result.
    """
    py_ver = detect_python_version(project_dir / ".venv")
    extensions = enumerate_enabled_extensions(project_dir)
    template = get_template("docker-compose.yml")
    rendered = render_compose(template, python_version=py_ver, extensions=extensions)
    out = project_dir / "docker" / "docker-compose.yml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
