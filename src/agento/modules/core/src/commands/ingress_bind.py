"""CLI command: ingress:bind — bind an inbound identity to an agent_view."""
from __future__ import annotations

import argparse


class IngressBindCommand:
    @property
    def name(self) -> str:
        return "ingress:bind"

    @property
    def help(self) -> str:
        return "Bind an inbound identity to an agent_view"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("type", help="Identity type (e.g. email, teams, api_client)")
        parser.add_argument("value", help="Identity value (e.g. user@example.com)")
        parser.add_argument("agent_view_code", help="Agent view code to bind to")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.ingress_identity import bind_identity
        from agento.framework.workspace import get_agent_view_by_code

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            agent_view = get_agent_view_by_code(conn, args.agent_view_code)
            if agent_view is None:
                print(f"Error: agent_view '{args.agent_view_code}' not found")
                return
            bind_identity(conn, args.type, args.value, agent_view.id)
            print(f"Bound {args.type}={args.value} → agent_view '{args.agent_view_code}' (id={agent_view.id})")
        finally:
            conn.close()
