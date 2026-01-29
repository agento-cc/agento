from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .config import AgentManagerConfig
from .models import AgentProvider, Token


def resolve_active_token(
    config: AgentManagerConfig,
    agent_type: AgentProvider,
) -> str | None:
    """Read the active symlink for an agent type. Returns the target path, or None."""
    link = Path(config.active_dir) / agent_type.value
    if not link.is_symlink():
        return None
    target = link.resolve()
    if not target.is_file():
        return None
    return str(target)


def update_active_token(
    config: AgentManagerConfig,
    agent_type: AgentProvider,
    token: Token,
    logger: logging.Logger | None = None,
) -> None:
    """Atomically update the active symlink for an agent type.

    Strategy: create temp symlink in active_dir, then os.rename() over the
    real one. os.rename() is atomic on POSIX when src and dst are on the
    same filesystem.
    """
    active_dir = Path(config.active_dir)
    active_dir.mkdir(parents=True, exist_ok=True)

    link_path = active_dir / agent_type.value
    target = token.credentials_path

    # mkstemp creates a file; remove it so we can create a symlink at that path.
    fd, tmp_path = tempfile.mkstemp(dir=str(active_dir), prefix=f".{agent_type.value}.")
    os.close(fd)
    os.unlink(tmp_path)
    os.symlink(target, tmp_path)
    os.rename(tmp_path, str(link_path))

    if logger:
        logger.info(
            f"Active token updated: agent_type={agent_type.value} "
            f"label={token.label} target={target}"
        )


def read_credentials(credentials_path: str) -> dict:
    """Read opaque credentials JSON from a token file."""
    with open(credentials_path) as f:
        return json.load(f)
