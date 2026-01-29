"""CLI command: ingress:unbind — remove an ingress identity binding."""
from __future__ import annotations

import argparse


class IngressUnbindCommand:
    @property
    def name(self) -> str:
        return "ingress:unbind"

    @property
    def help(self) -> str:
        return "Remove an ingress identity binding"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("type", help="Identity type (e.g. email, teams, api_client)")
        parser.add_argument("value", help="Identity value (e.g. user@example.com)")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.ingress_identity import unbind_identity

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            deleted = unbind_identity(conn, args.type, args.value)
            if deleted:
                print(f"Unbound {args.type}={args.value}")
            else:
                print(f"No binding found for {args.type}={args.value}")
        finally:
            conn.close()
