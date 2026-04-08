"""CLI command: tool:disable -- disable a tool in scoped config."""
from __future__ import annotations

import argparse


class ToolDisableCommand:
    @property
    def name(self) -> str:
        return "tool:disable"

    @property
    def shortcut(self) -> str:
        return "to:di"

    @property
    def help(self) -> str:
        return "Disable a tool (set tools/{name}/is_enabled = 0)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("tool_name", help="Name of the tool to disable")
        parser.add_argument(
            "--scope",
            default="default",
            choices=["default", "workspace", "agent_view"],
            help="Config scope (default: default)",
        )
        parser.add_argument(
            "--scope-id",
            dest="scope_id",
            type=int,
            default=0,
            help="Scope ID (default: 0)",
        )

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.scoped_config import scoped_config_set

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            path = f"tools/{args.tool_name}/is_enabled"
            scoped_config_set(
                conn,
                path,
                "0",
                scope=args.scope,
                scope_id=args.scope_id,
            )
            conn.commit()
            print(
                f"Disabled tool '{args.tool_name}' "
                f"(scope={args.scope}, scope_id={args.scope_id})"
            )
        finally:
            conn.close()
