"""Core build logic for composable workspace builds.

Materializes a pre-built directory per agent_view containing all config files,
instruction files, and skills. The consumer can then copy from the build dir
instead of regenerating everything per job.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from agento.framework.events import (
    WorkspaceBuildCompletedEvent,
    WorkspaceBuildFailedEvent,
    WorkspaceBuildStartedEvent,
)

logger = logging.getLogger(__name__)

BASE_WORKSPACE_DIR = os.environ.get("AGENTO_WORKSPACE_DIR", "/workspace")


def _dispatch(event_name: str, event: object) -> None:
    """Dispatch event via framework EventManager (swallows errors if not bootstrapped)."""
    try:
        from agento.framework.event_manager import get_event_manager
        get_event_manager().dispatch(event_name, event)
    except Exception:
        logger.debug("Event dispatch skipped for %s", event_name)

CLAUDE_MD_CONTENT = "# Instructions\n\nPlease read and follow [AGENTS.md](AGENTS.md).\n"

_INSTRUCTION_FILES = {
    "agent/instructions/agents_md": "AGENTS.md",
    "agent/instructions/soul_md": "SOUL.md",
}


@dataclass
class BuildResult:
    build_id: int
    build_dir: str
    checksum: str
    skipped: bool = False


def compute_build_checksum(
    scoped_overrides: dict,
    skill_checksums: list[str] | None = None,
) -> str:
    """Deterministic SHA-256 over sorted config values + skill checksums."""
    parts = []
    for path in sorted(scoped_overrides.keys()):
        value, _encrypted = scoped_overrides[path]
        parts.append(f"{path}={value}")
    if skill_checksums:
        parts.extend(sorted(skill_checksums))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _write_instruction_files(
    build_dir: Path,
    scoped_overrides: dict,
    workspace_dir: str = "/workspace",
) -> None:
    """Write AGENTS.md, SOUL.md, CLAUDE.md into build directory (inline, no module import)."""
    wd = Path(workspace_dir)
    for config_path, filename in _INSTRUCTION_FILES.items():
        entry = scoped_overrides.get(config_path)
        if entry is not None:
            value, _encrypted = entry
            if value:
                (build_dir / filename).write_text(value)
                continue
        workspace_file = wd / filename
        if workspace_file.is_file():
            shutil.copy2(workspace_file, build_dir / filename)
    (build_dir / "CLAUDE.md").write_text(CLAUDE_MD_CONTENT)


def _resolve_skills_dir() -> Path:
    """Resolve skills directory from skill module config or default."""
    try:
        from agento.framework.bootstrap import get_module_config
        cfg = get_module_config("skill")
        if cfg and isinstance(cfg, dict) and cfg.get("skills_dir"):
            return Path(cfg["skills_dir"])
    except Exception:
        pass
    return Path("workspace/.claude/skills")


def _get_enabled_skills(conn, agent_view_id, workspace_id):
    """Fetch enabled skills (soft dependency on skill module). Returns (skills, registry) or ([], None)."""
    import importlib
    try:
        registry = importlib.import_module("agento.modules.skill.src.registry")
    except (ImportError, ModuleNotFoundError):
        return [], None
    skills = registry.get_enabled_skills(conn, agent_view_id=agent_view_id, workspace_id=workspace_id)
    return skills, registry


def _write_skills_to_build(build_dir: Path, skills, registry, skills_dir: Path) -> None:
    """Write pre-fetched enabled skills into build dir."""
    if not skills or registry is None:
        return
    output_dir = build_dir / ".claude" / "skills"
    output_dir.mkdir(parents=True, exist_ok=True)
    for skill in skills:
        content = registry.get_skill_content(skill.name, skills_dir)
        if content:
            (output_dir / f"{skill.name}.md").write_text(content)


def execute_build(conn, agent_view_id: int) -> BuildResult:
    """Build a materialized workspace for an agent_view."""
    from agento.framework.agent_config_writer import populate_agent_configs
    from agento.framework.scoped_config import build_scoped_overrides
    from agento.framework.workspace import get_agent_view

    agent_view = get_agent_view(conn, agent_view_id)
    if agent_view is None:
        raise ValueError(f"agent_view {agent_view_id} not found")

    with conn.cursor() as cur:
        cur.execute("SELECT code FROM workspace WHERE id = %s", (agent_view.workspace_id,))
        ws_row = cur.fetchone()
    if ws_row is None:
        raise ValueError(f"workspace {agent_view.workspace_id} not found")
    workspace_code = ws_row["code"] if isinstance(ws_row, dict) else ws_row[0]

    overrides = build_scoped_overrides(
        conn, agent_view_id=agent_view_id, workspace_id=agent_view.workspace_id,
    )

    # Fetch enabled skills once (used for checksum + build)
    enabled_skills, skill_registry = _get_enabled_skills(
        conn, agent_view_id, agent_view.workspace_id,
    )
    skill_checksums = [s.checksum for s in enabled_skills]

    checksum = compute_build_checksum(overrides, skill_checksums)

    # Skip if identical build already exists
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, build_dir FROM workspace_build "
            "WHERE agent_view_id = %s AND checksum = %s AND status = 'ready'",
            (agent_view_id, checksum),
        )
        existing = cur.fetchone()
    if existing:
        logger.info(
            "Build %d already exists with checksum %s, skipping",
            existing["id"], checksum[:12],
        )
        result = BuildResult(
            build_id=existing["id"],
            build_dir=existing["build_dir"],
            checksum=checksum,
            skipped=True,
        )
        _dispatch("workspace_build_complete_after", WorkspaceBuildCompletedEvent(
            agent_view_id=agent_view_id, build_id=existing["id"],
            build_dir=existing["build_dir"], checksum=checksum, skipped=True,
        ))
        return result

    # Insert new build record
    base = Path(BASE_WORKSPACE_DIR) / workspace_code / agent_view.code / "builds"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workspace_build (agent_view_id, build_dir, checksum, status) "
            "VALUES (%s, %s, %s, 'building')",
            (agent_view_id, "", checksum),
        )
        build_id = cur.lastrowid
    conn.commit()

    _dispatch("workspace_build_start_after", WorkspaceBuildStartedEvent(
        agent_view_id=agent_view_id, build_id=build_id,
    ))

    build_dir = base / str(build_id)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspace_build SET build_dir = %s WHERE id = %s",
            (str(build_dir), build_id),
        )
    conn.commit()

    try:
        build_dir.mkdir(parents=True, exist_ok=True)

        # 1. Agent CLI configs (.claude.json, .mcp.json, .codex/config.toml)
        populate_agent_configs(build_dir, overrides, agent_view_id=agent_view_id)

        # 2. Instruction files (AGENTS.md, SOUL.md, CLAUDE.md)
        _write_instruction_files(build_dir, overrides)

        # 3. Skills (soft dependency)
        skills_dir = _resolve_skills_dir()
        _write_skills_to_build(build_dir, enabled_skills, skill_registry, skills_dir)

        # Mark as ready
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workspace_build SET status = 'ready' WHERE id = %s",
                (build_id,),
            )
        conn.commit()

        # Update 'current' symlink
        current_link = base.parent / "current"
        if current_link.is_symlink() or current_link.exists():
            current_link.unlink()
        current_link.symlink_to(build_dir)

        logger.info("Build %d ready at %s (checksum %s)", build_id, build_dir, checksum[:12])
        _dispatch("workspace_build_complete_after", WorkspaceBuildCompletedEvent(
            agent_view_id=agent_view_id, build_id=build_id,
            build_dir=str(build_dir), checksum=checksum,
        ))
        return BuildResult(build_id=build_id, build_dir=str(build_dir), checksum=checksum)

    except Exception as exc:
        _dispatch("workspace_build_fail_after", WorkspaceBuildFailedEvent(
            agent_view_id=agent_view_id, build_id=build_id, error=str(exc),
        ))
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workspace_build SET status = 'failed' WHERE id = %s",
                (build_id,),
            )
        conn.commit()
        raise

