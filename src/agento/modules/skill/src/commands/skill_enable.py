"""CLI command: skill:enable — enable a skill at given scope."""
from __future__ import annotations

import argparse


class SkillEnableCommand:
    @property
    def name(self) -> str:
        return "skill:enable"

    @property
    def shortcut(self) -> str:
        return "sk:en"

    @property
    def help(self) -> str:
        return "Enable a skill at given scope"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("skill_name", help="Skill name")
        parser.add_argument("--scope", default="default", choices=["default", "workspace", "agent_view"], help="Config scope")
        parser.add_argument("--scope-id", type=int, default=0, help="Scope ID")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.scoped_config import scoped_config_set

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            path = f"skill/{args.skill_name}/is_enabled"
            scoped_config_set(conn, path, "1", scope=args.scope, scope_id=args.scope_id)
            conn.commit()
            print(f"Enabled skill '{args.skill_name}' at scope={args.scope}, scope_id={args.scope_id}")
        finally:
            conn.close()
