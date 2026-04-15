"""Skill registry — scan from disk, sync to DB, query enabled skills."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    name: str
    path: str
    description: str
    checksum: str


@dataclass
class SyncResult:
    new: int
    updated: int
    unchanged: int


def scan_skills(skills_dir: Path) -> list[SkillInfo]:
    """Scan disk for skill directories containing SKILL.md."""
    if not skills_dir.is_dir():
        return []
    skills = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        content = skill_file.read_text()
        checksum = hashlib.sha256(content.encode()).hexdigest()
        # Description: first non-empty line after optional # heading
        description = ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped[:500]
                break
        skills.append(SkillInfo(
            name=entry.name,
            path=str(skill_file),
            description=description,
            checksum=checksum,
        ))
    return skills


def scan_skills_multi(skills_dirs: list[Path]) -> list[SkillInfo]:
    """Scan multiple directories for skills. First occurrence wins on name collision."""
    seen: set[str] = set()
    result: list[SkillInfo] = []
    for sdir in skills_dirs:
        for skill in scan_skills(sdir):
            if skill.name in seen:
                logger.warning(
                    "Skill name collision: '%s' from %s (skipping, already registered from earlier source)",
                    skill.name, sdir,
                )
                continue
            seen.add(skill.name)
            result.append(skill)
    return result


def sync_skills_multi(conn, skills_dirs: list[Path]) -> SyncResult:
    """Sync skills from multiple source directories. First occurrence wins."""
    scanned = scan_skills_multi(skills_dirs)
    result = _upsert_skills(conn, scanned)
    _dispatch_sync_event(str(skills_dirs), result)
    return result


def sync_skills(conn, skills_dir: Path) -> SyncResult:
    """Upsert scanned skills into skill_registry."""
    scanned = scan_skills(skills_dir)
    result = _upsert_skills(conn, scanned)
    _dispatch_sync_event(str(skills_dir), result)
    return result


def _upsert_skills(conn, scanned: list[SkillInfo]) -> SyncResult:
    """Upsert scanned skills into skill_registry (no event dispatch)."""
    new = updated = unchanged = 0

    with conn.cursor() as cur:
        for skill in scanned:
            cur.execute("SELECT id, checksum FROM skill_registry WHERE name = %s", (skill.name,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO skill_registry (name, path, description, checksum, synced_at) "
                    "VALUES (%s, %s, %s, %s, NOW())",
                    (skill.name, skill.path, skill.description, skill.checksum),
                )
                new += 1
            else:
                existing_checksum = row["checksum"] if isinstance(row, dict) else row[1]
                if existing_checksum != skill.checksum:
                    cur.execute(
                        "UPDATE skill_registry SET path=%s, description=%s, checksum=%s, synced_at=NOW() "
                        "WHERE name=%s",
                        (skill.path, skill.description, skill.checksum, skill.name),
                    )
                    updated += 1
                else:
                    unchanged += 1
    conn.commit()
    return SyncResult(new=new, updated=updated, unchanged=unchanged)


def _dispatch_sync_event(skills_dir_str: str, result: SyncResult) -> None:
    try:
        from agento.framework.event_manager import get_event_manager
        from agento.framework.events import SkillSyncCompletedEvent
        get_event_manager().dispatch("skill_sync_complete_after", SkillSyncCompletedEvent(
            skills_dir=skills_dir_str, new=result.new, updated=result.updated, unchanged=result.unchanged,
        ))
    except Exception:
        pass


def get_all_skills(conn) -> list[SkillInfo]:
    """Get all registered skills from DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, path, description, checksum FROM skill_registry ORDER BY name")
        rows = cur.fetchall()
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(SkillInfo(name=row["name"], path=row["path"], description=row["description"], checksum=row["checksum"]))
        else:
            result.append(SkillInfo(name=row[0], path=row[1], description=row[2], checksum=row[3]))
    return result


def get_enabled_skills(conn, agent_view_id: int | None = None, workspace_id: int | None = None) -> list[SkillInfo]:
    """Get skills that are enabled for the given scope."""
    from agento.framework.scoped_config import build_scoped_overrides

    all_skills = get_all_skills(conn)
    overrides = build_scoped_overrides(conn, agent_view_id=agent_view_id, workspace_id=workspace_id)

    enabled = []
    for skill in all_skills:
        entry = overrides.get(f"skill/{skill.name}/is_enabled")
        if entry is not None and entry[0] == "0":
            continue
        enabled.append(skill)
    return enabled


def get_skill_content(name: str, skills_dir: Path, path: str | None = None) -> str | None:
    """Read SKILL.md content from disk."""
    # Registered path takes priority — handles module skills with absolute paths
    if path:
        registered = Path(path)
        if registered.is_file():
            return registered.read_text()
    # Fallback: user workspace skills layout
    skill_file = skills_dir / name / "SKILL.md"
    if skill_file.is_file():
        return skill_file.read_text()
    return None
