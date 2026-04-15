"""Core build logic for composable workspace builds.

Materializes a pre-built directory per agent_view containing all config files,
instruction files, and skills. The consumer can then copy from the build dir
instead of regenerating everything per job.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from agento.framework.events import (
    WorkspaceBuildCompletedEvent,
    WorkspaceBuildFailedEvent,
    WorkspaceBuildStartedEvent,
)
from agento.framework.workspace_paths import BUILD_DIR, THEME_DIR

logger = logging.getLogger(__name__)


def _dispatch(event_name: str, event: object) -> None:
    """Dispatch event via framework EventManager (swallows errors if not bootstrapped)."""
    try:
        from agento.framework.event_manager import get_event_manager
        get_event_manager().dispatch(event_name, event)
    except Exception:
        logger.debug("Event dispatch skipped for %s", event_name)

CLAUDE_MD_CONTENT = "# Instructions\n\nPlease read and follow [AGENTS.md](AGENTS.md).\n"

_INSTRUCTION_FILES = {
    "agent_view/instructions/agents_md": "AGENTS.md",
    "agent_view/instructions/soul_md": "SOUL.md",
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
    *,
    building_strategy: str = "copy",
) -> str:
    """Deterministic SHA-256 over sorted config values + skill checksums + strategy."""
    parts = []
    for path in sorted(scoped_overrides.keys()):
        value, _encrypted = scoped_overrides[path]
        parts.append(f"{path}={value}")
    if skill_checksums:
        parts.extend(sorted(skill_checksums))
    parts.append(f"__building_strategy={building_strategy}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _write_instruction_files(
    build_dir: Path,
    scoped_overrides: dict,
) -> None:
    """Write AGENTS.md, SOUL.md from DB into build dir (theme fallback handled by _copy_theme)."""
    for config_path, filename in _INSTRUCTION_FILES.items():
        entry = scoped_overrides.get(config_path)
        if entry is not None:
            value, _encrypted = entry
            if value:
                (build_dir / filename).write_text(value)
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


def _copy_layer(source_dir: Path, dest_dir: Path) -> None:
    """Copy all non-underscore, non-dot prefixed items from source to dest."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.name.startswith((".", "_")):
            continue
        target = dest_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _copy_theme(build_dir: Path, workspace_code: str, agent_view_code: str) -> None:
    """Copy theme layers: base → workspace → agent_view (each overrides the previous)."""
    root = Path(THEME_DIR) / "_root"
    if not root.is_dir():
        return
    _copy_layer(root, build_dir)
    ws_dir = root / f"_{workspace_code}"
    if ws_dir.is_dir():
        _copy_layer(ws_dir, build_dir)
        av_dir = ws_dir / f"_{agent_view_code}"
        if av_dir.is_dir():
            _copy_layer(av_dir, build_dir)


def _copy_module_workspaces(
    build_dir: Path, workspace_code: str, agent_view_code: str,
    *, strategy: str = "copy",
) -> None:
    """Copy or symlink workspace/ directories from enabled modules into build (namespaced).

    Applies the same layered ``_`` prefix convention as theme: base content first,
    then workspace-scoped overlay, then agent_view-scoped overlay.
    When scope dirs exist, always uses copy (symlinks can't merge layers).
    """
    try:
        from agento.framework.bootstrap import get_manifests
        manifests = get_manifests()
    except Exception:
        return
    for manifest in manifests:
        mod_workspace = Path(manifest.path) / "workspace"
        if not mod_workspace.is_dir():
            continue
        dest = build_dir / "modules" / manifest.name
        has_scope_dirs = any(
            d.name.startswith("_") for d in mod_workspace.iterdir() if d.is_dir()
        )
        if has_scope_dirs or strategy == "copy":
            _copy_layer(mod_workspace, dest)
            ws_dir = mod_workspace / f"_{workspace_code}"
            if ws_dir.is_dir():
                _copy_layer(ws_dir, dest)
                av_dir = ws_dir / f"_{agent_view_code}"
                if av_dir.is_dir():
                    _copy_layer(av_dir, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(mod_workspace.resolve())


def _write_skills_to_build(build_dir: Path, skills, registry, skills_dir: Path) -> None:
    """Write pre-fetched enabled skills into build dir."""
    if not skills or registry is None:
        return
    output_dir = build_dir / ".claude" / "skills"
    output_dir.mkdir(parents=True, exist_ok=True)
    for skill in skills:
        content = registry.get_skill_content(skill.name, skills_dir, path=skill.path)
        if content:
            (output_dir / f"{skill.name}.md").write_text(content)


def execute_build(conn, agent_view_id: int) -> BuildResult:
    """Build a materialized workspace for an agent_view."""
    from agento.framework.agent_view_runtime import resolve_agent_view_runtime
    from agento.framework.config_writer import get_agent_config, get_config_writer
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

    # Resolve building strategy (copy or symlink) — scoped via overrides
    building_strategy = "copy"
    bs_entry = overrides.get("workspace_build/building_strategy")
    if bs_entry is not None:
        building_strategy = bs_entry[0]
    else:
        try:
            from agento.framework.bootstrap import get_module_config
            cfg = get_module_config("workspace_build")
            building_strategy = cfg.get("building_strategy", "copy")
        except Exception:
            pass

    checksum = compute_build_checksum(
        overrides, skill_checksums, building_strategy=building_strategy,
    )

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
    base = Path(BUILD_DIR) / workspace_code / agent_view.code / "builds"
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

        # 1. Theme as base layer (scaffolding, KnowledgeBase, etc.)
        _copy_theme(build_dir, workspace_code, agent_view.code)

        # 2. Agent CLI configs via provider-specific ConfigWriter
        runtime = resolve_agent_view_runtime(conn, agent_view_id)
        if runtime.provider:
            agent_config = get_agent_config(overrides)
            if agent_config:
                writer = get_config_writer(runtime.provider)
                writer.prepare_workspace(build_dir, agent_config, agent_view_id=agent_view_id)

        # 3. Instruction files (AGENTS.md, SOUL.md, CLAUDE.md)
        _write_instruction_files(build_dir, overrides)

        # 4. Module workspace assets (namespaced under modules/{name}/)
        _copy_module_workspaces(build_dir, workspace_code, agent_view.code, strategy=building_strategy)

        # 5. Skills (soft dependency)
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

