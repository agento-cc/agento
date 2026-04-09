"""Per-run isolated directory management for concurrent agent_view execution.

Each job gets its own run directory under workspace/runtime/.
Directories are created before execution and cleaned up after completion.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from agento.framework.workspace_paths import BUILD_DIR, RUNTIME_DIR

logger = logging.getLogger(__name__)


def build_run_dir(workspace_code: str, agent_view_code: str, job_id: int) -> Path:
    """Build the isolated run directory path for a single job execution."""
    return Path(RUNTIME_DIR) / workspace_code / agent_view_code / str(job_id)


def prepare_run_dir(run_dir: Path) -> None:
    """Create the run directory tree."""
    run_dir.mkdir(parents=True, exist_ok=True)


def cleanup_run_dir(run_dir: Path) -> None:
    """Remove the run directory after job completion."""
    try:
        if run_dir.exists():
            shutil.rmtree(run_dir)
            logger.debug("Cleaned up run dir %s", run_dir)
    except Exception:
        logger.warning("Failed to clean up run dir %s", run_dir, exc_info=True)


def get_current_build_dir(workspace_code: str, agent_view_code: str) -> Path | None:
    """Return the current build directory if the symlink exists and target is valid."""
    current_link = Path(BUILD_DIR) / workspace_code / agent_view_code / "current"
    if current_link.is_symlink():
        target = current_link.resolve()
        if target.is_dir():
            return target
    return None


# Config files/dirs that the agent CLI needs at cwd root — small, may be modified.
_COPY_FILES = {".claude.json", ".mcp.json", "CLAUDE.md", "AGENTS.md", "SOUL.md"}
_COPY_DIRS = {".claude", ".codex"}


def copy_build_to_run_dir(
    build_dir: Path,
    run_dir: Path,
    *,
    job_id: int | None = None,
    workspace_code: str | None = None,
    agent_view_code: str | None = None,
) -> None:
    """Thin bootstrap: copy small config files, symlink large readonly content.

    Injects job_id/ws/av into .mcp.json URLs so toolbox knows the runtime path.
    """
    for item in build_dir.iterdir():
        dest = run_dir / item.name
        if item.name in _COPY_FILES and item.is_file():
            shutil.copy2(item, dest)
        elif item.name in _COPY_DIRS and item.is_dir():
            shutil.copytree(item, dest)
        elif item.is_dir():
            dest.symlink_to(item.resolve())
        else:
            dest.symlink_to(item.resolve())

    # Inject runtime params into .mcp.json URLs
    if job_id is not None:
        _inject_runtime_params(run_dir, job_id, workspace_code or "", agent_view_code or "")


def _inject_runtime_params(
    run_dir: Path, job_id: int, workspace_code: str, agent_view_code: str,
) -> None:
    """Append job_id, ws, av query params to toolbox URLs in .mcp.json."""
    mcp_path = run_dir / ".mcp.json"
    if not mcp_path.is_file():
        return
    try:
        data = json.loads(mcp_path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    servers = data.get("mcpServers", {})
    extra = f"job_id={job_id}&ws={workspace_code}&av={agent_view_code}"
    for server_cfg in servers.values():
        url = server_cfg.get("url", "")
        if "/sse" in url or "/mcp" in url:
            sep = "&" if "?" in url else "?"
            server_cfg["url"] = f"{url}{sep}{extra}"
    mcp_path.write_text(json.dumps(data, indent=2))
