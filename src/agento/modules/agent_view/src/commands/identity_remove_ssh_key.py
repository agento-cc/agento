"""CLI command: agent_view:identity:remove-ssh-key — delete stored SSH key."""
from __future__ import annotations

import argparse
import sys

from agento.framework.scoped_config import Scope


class IdentityRemoveSshKeyCommand:
    @property
    def name(self) -> str:
        return "agent_view:identity:remove-ssh-key"

    @property
    def shortcut(self) -> str:
        return "av:id:rm"

    @property
    def help(self) -> str:
        return "Remove stored SSH key + public key + config for an agent_view"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("agent_view_code", help="Agent view code")
        parser.add_argument(
            "--scope", default=None,
            choices=[Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW],
        )
        parser.add_argument("--scope-id", dest="scope_id", type=int, default=None)

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection_or_exit

        from .identity_set_ssh_key import _resolve_scope

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            scope, scope_id = _resolve_scope(conn, args)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM core_config_data WHERE scope = %s AND scope_id = %s "
                    "AND path IN (%s, %s, %s, %s)",
                    (
                        scope, scope_id,
                        "agent_view/identity/ssh_private_key",
                        "agent_view/identity/ssh_public_key",
                        "agent_view/identity/ssh_config",
                        "agent_view/identity/ssh_known_hosts",
                    ),
                )
                removed = cur.rowcount
            conn.commit()
        finally:
            conn.close()

        if removed == 0:
            print(f"No SSH identity stored for {scope}/{scope_id}", file=sys.stderr)
            sys.exit(1)
        print(f"Removed {removed} SSH identity row(s) for {scope}/{scope_id}")
