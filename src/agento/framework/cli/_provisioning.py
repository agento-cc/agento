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

# Matches a uv.lock package source line:
#   source = { registry = "<path-or-url>" }
# Captures the path/URL so we can spot relative/absolute filesystem paths
# that won't resolve inside the cron container.
_LOCK_REGISTRY_LINE = re.compile(r'^source = \{ registry = "([^"]+)" \}', re.MULTILINE)


def find_links_for_local_install() -> list[str]:
    """Return --find-links args if agento-core was installed from a local wheel.

    When the CLI was installed via `uv tool install /path/to/wheel.whl` the
    dist-info contains a ``direct_url.json`` with a ``file://`` URL.  We pass
    the wheel's parent directory to `uv sync --find-links` so the project venv
    can resolve the same version without a PyPI lookup.  Returns [] when
    agento-core came from PyPI (no extra flags needed).
    """
    try:
        import json as _json
        from importlib.metadata import distribution

        dist = distribution("agento-core")
        text = dist.read_text("direct_url.json")
        if not text:
            return []
        data = _json.loads(text)
        url = data.get("url", "")
        if url.startswith("file://") and url.endswith(".whl"):
            wheel_path = Path(url[len("file://"):])
            if wheel_path.is_file():
                return ["--find-links", str(wheel_path.parent)]
    except Exception:
        pass
    return []


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


def localize_lockfile_for_container(
    project_dir: Path,
    cron_ctx: Path,
) -> None:
    """Inline local-wheel registries from the project's ``uv.lock`` into the cron context.

    When the CLI is installed from a local wheel (``uv tool install /path/to/*.whl``),
    ``find_links_for_local_install()`` adds ``--find-links`` to ``uv sync``. uv records
    the wheel's directory as a path-style ``source = { registry = "..." }`` in the
    project's ``uv.lock`` — relative to the project directory.

    Inside the cron container, that relative path navigates above ``/`` and uv refuses
    to normalize it. Fix by copying every locally-sourced wheel/sdist into
    ``cron/_local_dist/`` and rewriting the registry path in the cron context's
    ``uv.lock`` to ``_local_dist`` (relative to ``/opt/cron-agent/uv.lock``).

    Always creates ``cron/_local_dist/`` (with a ``.gitkeep``) so the Dockerfile's
    ``COPY ./_local_dist`` step succeeds even when no rewrites are needed.
    """
    local_dist = cron_ctx / "_local_dist"
    local_dist.mkdir(parents=True, exist_ok=True)
    (local_dist / ".gitkeep").touch()

    src_lock = project_dir / "uv.lock"
    dst_lock = cron_ctx / "uv.lock"
    if not src_lock.is_file() or not dst_lock.is_file():
        return

    text = dst_lock.read_text()
    rewrote = False
    for match in _LOCK_REGISTRY_LINE.finditer(text):
        registry = match.group(1)
        if registry.startswith(("http://", "https://")):
            continue

        # Filesystem registry — resolve relative to the project's uv.lock location.
        registry_path = (project_dir / registry).resolve()
        if not registry_path.is_dir():
            continue

        for entry in registry_path.iterdir():
            if entry.is_file() and entry.suffix in (".whl", ".gz", ".zip"):
                shutil.copy2(entry, local_dist / entry.name)

        text = text.replace(match.group(0), 'source = { registry = "_local_dist" }')
        rewrote = True

    if rewrote:
        dst_lock.write_text(text)


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

    # If the project venv was hydrated from a local wheel (developer build),
    # uv.lock contains a path-style registry that won't resolve inside the
    # cron container. Inline those wheels into the cron context.
    localize_lockfile_for_container(project_dir, target / "cron")

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
