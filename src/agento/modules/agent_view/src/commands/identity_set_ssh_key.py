"""CLI command: agent_view:identity:set-ssh-key — store an SSH private key (encrypted)."""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from agento.framework.scoped_config import Scope, scoped_config_set


class IdentitySetSshKeyCommand:
    @property
    def name(self) -> str:
        return "agent_view:identity:set-ssh-key"

    @property
    def shortcut(self) -> str:
        return "av:id:ssh"

    @property
    def help(self) -> str:
        return "Store an SSH private key for an agent_view (encrypted at rest)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("agent_view_code", help="Agent view code (shortcut for --scope agent_view)")
        parser.add_argument("private_key_path", help="Path to the SSH private key file (e.g. ~/.ssh/agent_dev_01)")
        parser.add_argument(
            "--public-key-path", dest="public_key_path", default=None,
            help="Path to the matching public key (default: <private>.pub if present)",
        )
        parser.add_argument(
            "--scope", default=None,
            choices=[Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW],
            help="Config scope (default: agent_view when agent_view_code given)",
        )
        parser.add_argument("--scope-id", dest="scope_id", type=int, default=None)

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection_or_exit

        private_key = Path(args.private_key_path).expanduser()
        if not private_key.is_file():
            print(f"Error: private key file not found: {private_key}", file=sys.stderr)
            sys.exit(1)
        private_text = private_key.read_text()
        if "PRIVATE KEY" not in private_text:
            print(f"Error: {private_key} does not look like an OpenSSH/PEM private key", file=sys.stderr)
            sys.exit(1)

        public_text: str | None = None
        pub_path = (
            Path(args.public_key_path).expanduser() if args.public_key_path
            else private_key.with_suffix(private_key.suffix + ".pub") if private_key.suffix
            else Path(str(private_key) + ".pub")
        )
        if pub_path.is_file():
            public_text = pub_path.read_text()

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            scope, scope_id = _resolve_scope(conn, args)
            scoped_config_set(
                conn, "agent_view/identity/ssh_private_key",
                private_text, scope=scope, scope_id=scope_id, encrypted=True,
            )
            if public_text is not None:
                scoped_config_set(
                    conn, "agent_view/identity/ssh_public_key",
                    public_text, scope=scope, scope_id=scope_id,
                )
            conn.commit()
        finally:
            conn.close()

        fingerprint = _ssh_fingerprint(private_key, public_text)
        pub_note = "" if public_text is None else f" (pub: {fingerprint})"
        print(f"Stored SSH private key for {scope}/{scope_id}{pub_note}")


def _resolve_scope(conn, args):
    if args.scope is not None:
        return args.scope, (args.scope_id or 0)
    from agento.framework.workspace import get_agent_view_by_code
    av = get_agent_view_by_code(conn, args.agent_view_code)
    if av is None:
        raise SystemExit(f"Error: agent_view '{args.agent_view_code}' not found")
    return Scope.AGENT_VIEW, av.id


def _ssh_fingerprint(private_key_path: Path, public_text: str | None) -> str:
    """Best-effort SHA256 fingerprint — falls back to a short hash of the pub key text."""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(private_key_path)],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip().split()[1]
    except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
        if public_text:
            digest = hashlib.sha256(public_text.encode()).hexdigest()[:16]
            return f"sha256:{digest}"
        return "unknown"
