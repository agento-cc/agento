"""Write per-run instruction files (AGENTS.md, SOUL.md, CLAUDE.md) from scoped config.

Fallback chain: DB (agent_view → workspace → global) → workspace file on disk.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_MD_CONTENT = "# Instructions\n\nPlease read and follow [AGENTS.md](AGENTS.md).\n"

_FILES = {
    "agent/instructions/agents_md": "AGENTS.md",
    "agent/instructions/soul_md": "SOUL.md",
}


def write_instruction_files(
    run_dir: str | Path,
    scoped_overrides: dict[str, tuple[str, bool]],
    workspace_dir: str | Path = "/workspace",
) -> None:
    """Write AGENTS.md, SOUL.md, and CLAUDE.md into a run directory.

    For each file: use DB config value if present, otherwise copy from workspace_dir.
    CLAUDE.md is always written (points Claude Code to AGENTS.md).
    """
    rd = Path(run_dir)
    wd = Path(workspace_dir)

    for config_path, filename in _FILES.items():
        entry = scoped_overrides.get(config_path)
        if entry is not None:
            value, _encrypted = entry
            if value:
                (rd / filename).write_text(value)
                logger.debug("Wrote %s from scoped config", filename)
                continue

        # Fallback: copy from workspace directory
        workspace_file = wd / filename
        if workspace_file.is_file():
            shutil.copy2(workspace_file, rd / filename)
            logger.debug("Copied %s from workspace", filename)

    # CLAUDE.md always written — Claude Code reads it from cwd
    (rd / "CLAUDE.md").write_text(CLAUDE_MD_CONTENT)
