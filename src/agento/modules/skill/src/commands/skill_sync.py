"""CLI command: skill:sync — scan skills from disk and sync to registry."""
from __future__ import annotations

import argparse
from pathlib import Path


class SkillSyncCommand:
    @property
    def name(self) -> str:
        return "skill:sync"

    @property
    def shortcut(self) -> str:
        return "sk:sy"

    @property
    def help(self) -> str:
        return "Scan skills from disk and sync to registry"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import get_manifests, get_module_config
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection

        from ..registry import sync_skills_multi

        db_config, _, _ = _load_framework_config()

        # User skills dir (highest priority)
        cfg = get_module_config("skill") or {}
        user_skills_dir = Path(cfg.get("skills_dir", "workspace/.claude/skills"))

        # Collect skill dirs: user first, then enabled modules
        skills_dirs: list[Path] = [user_skills_dir]
        try:
            for manifest in get_manifests():
                mod_skills = Path(manifest.path) / "skills"
                if mod_skills.is_dir():
                    skills_dirs.append(mod_skills)
        except Exception:
            pass

        conn = get_connection(db_config)
        try:
            result = sync_skills_multi(conn, skills_dirs)
            print(f"Synced: {result.new} new, {result.updated} updated, {result.unchanged} unchanged")
        finally:
            conn.close()
