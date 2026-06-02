"""Persistent HOME path helpers shared by workspace builds and per-run HOME dirs."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .workspace_paths import BUILD_DIR


def state_dir(
    workspace_code: str,
    agent_view_code: str,
    *,
    build_root: str | Path = BUILD_DIR,
) -> Path:
    return Path(build_root) / workspace_code / agent_view_code / "state"


def ensure_state_dir(
    workspace_code: str,
    agent_view_code: str,
    persistent_paths: list[str],
    *,
    build_root: str | Path = BUILD_DIR,
) -> Path:
    """Create the per-agent_view persistent ``state/`` directory."""
    state = state_dir(workspace_code, agent_view_code, build_root=build_root)
    state.mkdir(parents=True, exist_ok=True)
    for rel in persistent_paths:
        (state / rel).mkdir(parents=True, exist_ok=True)
    return state


def link_persistent_paths(
    home_dir: Path,
    state_dir: Path,
    persistent_paths: list[str],
) -> None:
    """Symlink declared persistent HOME paths to shared per-agent_view state."""
    for rel in persistent_paths:
        home_target = home_dir / rel
        state_target = state_dir / rel
        home_target.parent.mkdir(parents=True, exist_ok=True)
        if home_target.is_symlink() or home_target.exists():
            if home_target.is_dir() and not home_target.is_symlink():
                shutil.rmtree(home_target)
            else:
                home_target.unlink()
        rel_target = os.path.relpath(state_target, home_target.parent)
        home_target.symlink_to(rel_target)
