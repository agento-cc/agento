"""Per-job artifacts directory management.

Each job gets its own artifacts directory under workspace/artifacts/.
It contains the copied config files + symlinks to build assets, and holds
any per-job outputs the agent or toolbox drops (screenshots, videos, session
scratch). Directories are created at job start; on clean completion they are
removed, but crashed jobs leave their artifacts dir behind for inspection.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from agento.framework.workspace_paths import ARTIFACTS_DIR, BUILD_DIR

logger = logging.getLogger(__name__)


def build_artifacts_dir(workspace_code: str, agent_view_code: str, job_id: int) -> Path:
    """Build the artifacts directory path for a single job execution."""
    return Path(ARTIFACTS_DIR) / workspace_code / agent_view_code / str(job_id)


def prepare_artifacts_dir(artifacts_dir: Path) -> None:
    """Create the artifacts directory tree, cleaning any stale contents from prior attempts."""
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)


def cleanup_artifacts_dir(artifacts_dir: Path) -> None:
    """Remove the artifacts directory after successful job completion."""
    try:
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
            logger.debug("Cleaned up artifacts dir %s", artifacts_dir)
    except Exception:
        logger.warning("Failed to clean up artifacts dir %s", artifacts_dir, exc_info=True)


def get_current_build_dir(workspace_code: str, agent_view_code: str) -> Path | None:
    """Return the current build directory if the symlink exists and target is valid."""
    current_link = Path(BUILD_DIR) / workspace_code / agent_view_code / "current"
    if current_link.is_symlink():
        target = current_link.resolve()
        if target.is_dir():
            return target
    return None


# Universal instruction files (agent-agnostic) — always copied so per-job edits are isolated.
_UNIVERSAL_COPY_FILES = {"CLAUDE.md", "AGENTS.md", "SOUL.md"}


def copy_build_to_artifacts_dir(
    build_dir: Path,
    artifacts_dir: Path,
    *,
    job_id: int | None = None,
    provider: str | None = None,
) -> None:
    """Thin bootstrap: copy small config files, symlink large readonly content.

    Files/dirs owned by registered ConfigWriters are copied (so per-job
    runtime params can be injected). Everything else is symlinked.
    Dispatches runtime param injection to the provider's ConfigWriter.
    """
    from agento.framework.config_writer import all_owned_paths
    owned_files, owned_dirs = all_owned_paths(provider)
    copy_files = owned_files | _UNIVERSAL_COPY_FILES

    for item in build_dir.iterdir():
        dest = artifacts_dir / item.name
        if item.name in copy_files and item.is_file():
            shutil.copy2(item, dest)
        elif item.name in owned_dirs and item.is_dir():
            shutil.copytree(item, dest)
        elif item.is_dir():
            dest.symlink_to(item.resolve())
        else:
            dest.symlink_to(item.resolve())

    # Inject runtime params via provider-specific ConfigWriter
    if job_id is not None and provider is not None:
        try:
            from agento.framework.config_writer import get_config_writer
            writer = get_config_writer(provider)
            writer.inject_runtime_params(artifacts_dir, job_id=job_id)
        except KeyError:
            logger.warning("No ConfigWriter for provider %r, skipping runtime param injection", provider)
