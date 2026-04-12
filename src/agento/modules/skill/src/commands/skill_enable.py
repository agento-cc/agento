"""CLI command: skill:enable — enable a skill at given scope."""
from __future__ import annotations

import argparse

from agento.framework.scoped_config import Scope


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
        parser.add_argument("--agent-view", dest="agent_view_code", default=None, help="Agent view code (shortcut for --scope agent_view)")
        parser.add_argument("--scope", default=Scope.DEFAULT, choices=[Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW], help="Config scope")
        parser.add_argument("--scope-id", type=int, default=0, help="Scope ID")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.scoped_config import scoped_config_set

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            scope, scope_id = _resolve_scope(conn, args)
            path = f"skill/{args.skill_name}/is_enabled"
            scoped_config_set(conn, path, "1", scope=scope, scope_id=scope_id)
            conn.commit()
            print(f"Enabled skill '{args.skill_name}' at scope={scope}, scope_id={scope_id}")
        finally:
            conn.close()


def _resolve_scope(conn, args):
    """Resolve scope from --agent-view shortcut or explicit --scope/--scope-id."""
    if args.agent_view_code:
        from agento.framework.workspace import get_agent_view_by_code
        av = get_agent_view_by_code(conn, args.agent_view_code)
        if av is None:
            raise SystemExit(f"Error: agent_view '{args.agent_view_code}' not found")
        return Scope.AGENT_VIEW, av.id
    return args.scope, args.scope_id
