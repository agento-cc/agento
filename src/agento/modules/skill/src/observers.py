"""Observers for the skill module."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SkillSyncOnSetupObserver:
    """Auto-sync skills from disk after setup:upgrade completes."""

    def execute(self, event) -> None:
        if event.dry_run:
            return

        try:
            from pathlib import Path

            from agento.framework.bootstrap import get_manifests, get_module_config
            from agento.framework.database_config import DatabaseConfig
            from agento.framework.db import get_connection

            from .registry import sync_skills_multi

            cfg = get_module_config("skill") or {}
            user_skills_dir = Path(cfg.get("skills_dir", "workspace/.claude/skills"))

            skills_dirs: list[Path] = [user_skills_dir]
            try:
                for manifest in get_manifests():
                    mod_skills = Path(manifest.path) / "skills"
                    if mod_skills.is_dir():
                        skills_dirs.append(mod_skills)
            except Exception:
                pass

            conn = get_connection(DatabaseConfig.from_env())
            try:
                result = sync_skills_multi(conn, skills_dirs)
                print(
                    f"Skills synced: {result.new} new, "
                    f"{result.updated} updated, {result.unchanged} unchanged"
                )
            finally:
                conn.close()

        except Exception:
            logger.warning("skill: failed to sync skills during setup:upgrade (non-fatal)")
