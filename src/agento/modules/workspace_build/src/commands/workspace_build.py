"""CLI command: workspace:build — build materialized workspace for agent_view(s)."""
from __future__ import annotations

import argparse


class WorkspaceBuildCommand:
    @property
    def name(self) -> str:
        return "workspace:build"

    @property
    def shortcut(self) -> str:
        return "ws:b"

    @property
    def help(self) -> str:
        return "Build materialized workspace for agent_view(s)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--agent-view", help="Agent view code to build for")
        group.add_argument("--all", action="store_true", help="Build for all active agent_views")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild even if a matching build already exists",
        )

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.workspace import get_active_agent_views, get_agent_view_by_code

        from ..builder import execute_build

        def _verb(result) -> str:
            if args.force:
                return "Built (forced)"
            return "Skipped (unchanged)" if result.skipped else "Built"

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            if args.agent_view:
                agent_view = get_agent_view_by_code(conn, args.agent_view)
                if agent_view is None:
                    print(f"Error: agent_view '{args.agent_view}' not found")
                    return
                result = execute_build(conn, agent_view.id, force=args.force)
                print(f"{_verb(result)}: build {result.build_id} at {result.build_dir} (checksum {result.checksum[:12]})")
            else:
                agent_views = get_active_agent_views(conn)
                if not agent_views:
                    print("No active agent_views found")
                    return
                for av in agent_views:
                    result = execute_build(conn, av.id, force=args.force)
                    print(f"  {av.code}: {_verb(result)} — build {result.build_id} (checksum {result.checksum[:12]})")
        finally:
            conn.close()
