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
from typing import Literal

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

# Bump when the on-disk build layout changes in a backwards-incompatible way;
# mixed into the checksum so existing builds invalidate automatically on upgrade.
_SKILLS_LAYOUT_VERSION = "dir_v1"

# Recursive manifest descent cap — dirs colliding past this depth collapse to latest-wins.
_MAX_MANIFEST_DEPTH = 10

_SOURCES = ("theme", "modules", "skills")
_STRATEGY_VALUES = ("copy", "symlink")

Strategy = Literal["copy", "symlink"]
Kind = Literal["file", "dir"]

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
    strategies: dict[str, str] | None = None,
) -> str:
    """Deterministic SHA-256 over sorted config values + skill checksums + per-source strategies."""
    parts = []
    for path in sorted(scoped_overrides.keys()):
        value, _encrypted = scoped_overrides[path]
        parts.append(f"{path}={value}")
    if skill_checksums:
        parts.extend(sorted(skill_checksums))
    effective = {s: "copy" for s in _SOURCES}
    if strategies:
        for k, v in strategies.items():
            if k in effective:
                effective[k] = v
    for source in _SOURCES:
        parts.append(f"__strategy/{source}={effective[source]}")
    parts.append(f"__skills_layout={_SKILLS_LAYOUT_VERSION}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _write_instruction_files(
    build_dir: Path,
    scoped_overrides: dict,
) -> None:
    """Write AGENTS.md, SOUL.md, CLAUDE.md; unlink first so a prior theme symlink is not followed."""
    for config_path, filename in _INSTRUCTION_FILES.items():
        entry = scoped_overrides.get(config_path)
        if entry is not None:
            value, _encrypted = entry
            if value:
                target = build_dir / filename
                target.unlink(missing_ok=True)
                target.write_text(value)
    claude_target = build_dir / "CLAUDE.md"
    claude_target.unlink(missing_ok=True)
    claude_target.write_text(CLAUDE_MD_CONTENT)


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


def _kind_of(path: Path) -> Kind:
    return "dir" if path.is_dir() else "file"


def build_manifest(
    layers: list[Path | None],
    depth: int = 0,
) -> dict[str, tuple[Path, Kind]]:
    """Merge N ordered layers (base→specific) into a relative-path → (source, kind) manifest."""
    items_by_name: dict[str, list[Path]] = {}
    for layer in layers:
        if layer is None or not layer.is_dir():
            continue
        for item in layer.iterdir():
            if item.name.startswith((".", "_")):
                continue
            items_by_name.setdefault(item.name, []).append(item)

    manifest: dict[str, tuple[Path, Kind]] = {}
    for name, occurrences in items_by_name.items():
        latest = occurrences[-1]
        if len(occurrences) == 1:
            manifest[name] = (latest, _kind_of(latest))
            continue

        all_dirs = all(o.is_dir() for o in occurrences)
        if not all_dirs:
            manifest[name] = (latest, _kind_of(latest))
            continue

        if depth >= _MAX_MANIFEST_DEPTH:
            manifest[name] = (latest, "dir")
            continue

        sub = build_manifest(occurrences, depth + 1)
        for sub_rel, sub_val in sub.items():
            manifest[f"{name}/{sub_rel}"] = sub_val

    return manifest


def apply_manifest(
    manifest: dict[str, tuple[Path, Kind]],
    target_dir: Path,
    strategy: Strategy,
) -> None:
    """Write manifest entries into ``target_dir`` via copy or symlink; parent dirs are always real."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, (src, kind) in manifest.items():
        target = target_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        if strategy == "copy":
            if kind == "file":
                shutil.copy2(src, target)
            else:
                shutil.copytree(src, target)
        else:
            target.symlink_to(src.resolve())


def _theme_layers(workspace_code: str, agent_view_code: str) -> list[Path]:
    root = Path(THEME_DIR)
    if not root.is_dir():
        return []
    layers: list[Path] = [root]
    ws_dir = root / f"_{workspace_code}"
    if ws_dir.is_dir():
        layers.append(ws_dir)
        av_dir = ws_dir / f"_{agent_view_code}"
        if av_dir.is_dir():
            layers.append(av_dir)
    return layers


def _module_layers(
    module_workspace: Path,
    workspace_code: str,
    agent_view_code: str,
) -> list[Path]:
    layers: list[Path] = [module_workspace]
    ws_dir = module_workspace / f"_{workspace_code}"
    if ws_dir.is_dir():
        layers.append(ws_dir)
        av_dir = ws_dir / f"_{agent_view_code}"
        if av_dir.is_dir():
            layers.append(av_dir)
    return layers


def _copy_theme(
    build_dir: Path,
    workspace_code: str,
    agent_view_code: str,
    *,
    strategy: Strategy = "copy",
) -> None:
    layers = _theme_layers(workspace_code, agent_view_code)
    if not layers:
        return
    manifest = build_manifest(layers)
    apply_manifest(manifest, build_dir, strategy)


def _copy_module_workspaces(
    build_dir: Path,
    workspace_code: str,
    agent_view_code: str,
    *,
    strategy: Strategy = "copy",
) -> None:
    try:
        from agento.framework.bootstrap import get_manifests
        manifests = get_manifests()
    except Exception:
        return
    for manifest_entry in manifests:
        mod_workspace = Path(manifest_entry.path) / "workspace"
        if not mod_workspace.is_dir():
            continue
        dest = build_dir / "modules" / manifest_entry.name
        layers = _module_layers(mod_workspace, workspace_code, agent_view_code)
        manifest = build_manifest(layers)
        apply_manifest(manifest, dest, strategy)


def _write_skills_to_build(
    build_dir: Path,
    skills,
    registry,
    skills_dir: Path,
    *,
    strategy: Strategy = "copy",
) -> None:
    if not skills or registry is None:
        return
    output_dir = build_dir / ".claude" / "skills"
    output_dir.mkdir(parents=True, exist_ok=True)
    for skill in skills:
        source_dir: Path | None = None
        if skill.path:
            parent = Path(skill.path).parent
            if parent.is_dir():
                source_dir = parent
        if source_dir is None:
            candidate = skills_dir / skill.name
            if candidate.is_dir():
                source_dir = candidate
        if source_dir is None:
            logger.warning("Skill %r source directory not found — skipping", skill.name)
            continue
        manifest = {skill.name: (source_dir, "dir")}
        apply_manifest(manifest, output_dir, strategy)


def _create_agents_skills_symlink(build_dir: Path) -> None:
    """Create .agents/skills → ../.claude/skills symlink for Codex compatibility."""
    claude_skills = build_dir / ".claude" / "skills"
    if not claude_skills.is_dir():
        return
    agents_dir = build_dir / ".agents"
    agents_dir.mkdir(exist_ok=True)
    symlink = agents_dir / "skills"
    if symlink.is_symlink() or symlink.exists():
        symlink.unlink()
    symlink.symlink_to(Path("..") / ".claude" / "skills")


def _read_strategy(conn, source: str) -> Strategy:
    """Read workspace_build/strategy/{source} from global scope only, falling back to config.json."""
    if source not in _SOURCES:
        raise ValueError(f"Unknown workspace_build source: {source!r}")
    path = f"workspace_build/strategy/{source}"

    value: str | None = None
    if conn is not None:
        try:
            from agento.framework.scoped_config import Scope, load_scoped_db_overrides
            global_overrides = load_scoped_db_overrides(conn, Scope.DEFAULT, 0)
            entry = global_overrides.get(path)
            if entry is not None:
                value = entry[0]
        except Exception:
            logger.debug("Failed to read strategy/%s from DB; falling back to config.json", source)

    if value is None:
        try:
            from agento.framework.bootstrap import get_module_config
            cfg = get_module_config("workspace_build") or {}
            value = cfg.get(f"strategy/{source}")
        except Exception:
            value = None

    if value not in _STRATEGY_VALUES:
        if value is not None:
            logger.warning(
                "Invalid workspace_build strategy for %s: %r — falling back to 'copy'",
                source, value,
            )
        value = "copy"
    return value  # type: ignore[return-value]


def _resolve_strategies(conn) -> dict[str, Strategy]:
    return {source: _read_strategy(conn, source) for source in _SOURCES}


def execute_build(conn, agent_view_id: int, *, force: bool = False) -> BuildResult:
    """Build a materialized workspace for an agent_view.

    When ``force=True``, bypass the "identical build already exists" skip check,
    delete any prior same-checksum build directory from disk, retire its DB row,
    and always produce a fresh ``build_id``. Useful when something outside the
    checksum inputs has changed (manual theme edits, external template updates).
    """
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

    # Resolve per-source strategies (global-scope only).
    strategies = _resolve_strategies(conn)

    checksum = compute_build_checksum(
        overrides, skill_checksums, strategies=strategies,
    )

    # Skip if identical build already exists AND its build_dir is intact on disk.
    # When force=True, look up the prior build to clean it up, then always rebuild.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, build_dir FROM workspace_build "
            "WHERE agent_view_id = %s AND checksum = %s AND status = 'ready'",
            (agent_view_id, checksum),
        )
        existing = cur.fetchone()
    if not force and existing and existing["build_dir"] and Path(existing["build_dir"]).is_dir():
        logger.info(
            "Build %d already exists with checksum %s, skipping",
            existing["id"], checksum[:12],
        )
        existing_build_dir = Path(existing["build_dir"])
        current_link = existing_build_dir.parent.parent / "current"
        if not current_link.is_symlink() or current_link.resolve() != existing_build_dir.resolve():
            if current_link.is_symlink() or current_link.exists():
                current_link.unlink()
            current_link.symlink_to(existing_build_dir)
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
    if existing:
        # Either disk is gone (stale record) or force=True. Retire the old record
        # and clean up any on-disk remnants so the new build owns the checksum.
        if force:
            logger.info(
                "Force rebuild: retiring prior build %d (checksum %s) and cleaning %s",
                existing["id"], checksum[:12], existing["build_dir"],
            )
        else:
            logger.warning(
                "Build %d marked ready but build_dir %s is missing — rebuilding",
                existing["id"], existing["build_dir"],
            )
        if existing["build_dir"]:
            shutil.rmtree(existing["build_dir"], ignore_errors=True)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workspace_build SET status = 'failed' WHERE id = %s",
                (existing["id"],),
            )
        conn.commit()

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
        if build_dir.exists():
            # lastrowid collisions shouldn't happen, but guarantee a clean dest dir.
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)

        # 1. Theme as base layer (scaffolding, KnowledgeBase, etc.)
        _copy_theme(build_dir, workspace_code, agent_view.code, strategy=strategies["theme"])

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
        _copy_module_workspaces(
            build_dir, workspace_code, agent_view.code, strategy=strategies["modules"],
        )

        # 5. Skills (soft dependency)
        skills_dir = _resolve_skills_dir()
        _write_skills_to_build(
            build_dir, enabled_skills, skill_registry, skills_dir,
            strategy=strategies["skills"],
        )

        # 6. .agents/skills symlink → .claude/skills (Codex compatibility)
        _create_agents_skills_symlink(build_dir)

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
