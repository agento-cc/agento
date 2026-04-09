"""CLI command: workspace:build-status — show workspace build status."""
from __future__ import annotations

import argparse


class WorkspaceBuildStatusCommand:
    @property
    def name(self) -> str:
        return "workspace:build-status"

    @property
    def shortcut(self) -> str:
        return "ws:bs"

    @property
    def help(self) -> str:
        return "Show workspace build status"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agent-view", help="Filter by agent view code")

    def execute(self, args: argparse.Namespace) -> None:
        from pathlib import Path

        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.workspace import get_agent_view_by_code

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            query = (
                "SELECT wb.id, av.code AS agent_view_code, wb.checksum, "
                "wb.status, wb.build_dir, wb.created_at "
                "FROM workspace_build wb "
                "JOIN agent_view av ON av.id = wb.agent_view_id"
            )
            params: list = []

            if args.agent_view:
                agent_view = get_agent_view_by_code(conn, args.agent_view)
                if agent_view is None:
                    print(f"Error: agent_view '{args.agent_view}' not found")
                    return
                query += " WHERE wb.agent_view_id = %s"
                params.append(agent_view.id)

            query += " ORDER BY wb.created_at DESC LIMIT 20"

            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            if not rows:
                print("No builds found")
                return

            print(f"{'ID':>5}  {'Agent View':<20}  {'Checksum':<14}  {'Status':<10}  {'Current':>7}  {'Created At'}")
            print("-" * 90)
            for row in rows:
                build_dir = Path(row["build_dir"]) if row["build_dir"] else None
                is_current = ""
                if build_dir:
                    current_link = build_dir.parent.parent / "current"
                    if current_link.is_symlink():
                        is_current = "*" if current_link.resolve() == build_dir.resolve() else ""
                print(
                    f"{row['id']:>5}  {row['agent_view_code']:<20}  "
                    f"{row['checksum'][:12]:<14}  {row['status']:<10}  "
                    f"{is_current:>7}  {row['created_at']}"
                )
        finally:
            conn.close()
