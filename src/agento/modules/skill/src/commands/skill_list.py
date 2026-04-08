"""CLI command: skill:list — list registered skills with enabled/disabled status."""
from __future__ import annotations

import argparse


class SkillListCommand:
    @property
    def name(self) -> str:
        return "skill:list"

    @property
    def shortcut(self) -> str:
        return "sk:li"

    @property
    def help(self) -> str:
        return "List registered skills with enabled/disabled status"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agent-view", dest="agent_view_code", default=None, help="Agent view code for scoped status")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.scoped_config import build_scoped_overrides
        from agento.framework.workspace import get_agent_view_by_code

        from ..registry import get_all_skills

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            all_skills = get_all_skills(conn)
            if not all_skills:
                print("No skills registered. Run skill:sync first.")
                return

            agent_view_id = None
            workspace_id = None
            if args.agent_view_code:
                agent_view = get_agent_view_by_code(conn, args.agent_view_code)
                if agent_view is None:
                    print(f"Error: agent_view '{args.agent_view_code}' not found")
                    return
                agent_view_id = agent_view.id
                workspace_id = agent_view.workspace_id

            overrides = build_scoped_overrides(conn, agent_view_id=agent_view_id, workspace_id=workspace_id)

            for skill in all_skills:
                entry = overrides.get(f"skill/{skill.name}/is_enabled")
                status = "disabled" if entry is not None and entry[0] == "0" else "enabled"
                desc = skill.description[:60] if skill.description else ""
                print(f"  {skill.name:<30} {status:<10} {desc}")
        finally:
            conn.close()
