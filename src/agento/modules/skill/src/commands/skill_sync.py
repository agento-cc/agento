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
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection

        from ..registry import sync_skills

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            skills_dir = Path("app/skills")
            result = sync_skills(conn, skills_dir)
            print(f"Synced: {result.new} new, {result.updated} updated, {result.unchanged} unchanged")
        finally:
            conn.close()
