"""CLI command: agent_view:identity:show — display SSH identity info (never the private key)."""
from __future__ import annotations

import argparse
import hashlib
import sys

from agento.framework.scoped_config import build_scoped_overrides


class IdentityShowCommand:
    @property
    def name(self) -> str:
        return "agent_view:identity:show"

    @property
    def shortcut(self) -> str:
        return "av:id:sh"

    @property
    def help(self) -> str:
        return "Show stored SSH identity (public key + fingerprint; private key is never dumped)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("agent_view_code", help="Agent view code")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection_or_exit
        from agento.framework.encryptor import get_encryptor
        from agento.framework.workspace import get_agent_view_by_code

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            av = get_agent_view_by_code(conn, args.agent_view_code)
            if av is None:
                print(f"Error: agent_view '{args.agent_view_code}' not found", file=sys.stderr)
                sys.exit(1)

            overrides = build_scoped_overrides(
                conn, agent_view_id=av.id, workspace_id=av.workspace_id,
            )
        finally:
            conn.close()

        private_entry = overrides.get("agent_view/identity/ssh_private_key")
        public_entry = overrides.get("agent_view/identity/ssh_public_key")
        config_entry = overrides.get("agent_view/identity/ssh_config")
        known_hosts_entry = overrides.get("agent_view/identity/ssh_known_hosts")

        if private_entry is None and public_entry is None:
            print(f"No SSH identity stored for agent_view '{av.code}'")
            return

        print(f"agent_view: {av.code} (id={av.id})")
        if private_entry is not None:
            value, encrypted = private_entry
            try:
                plaintext = get_encryptor().decrypt(value) if encrypted else value
                fp = _derive_fingerprint(plaintext)
            except Exception:
                fp = "<unable to decrypt>"
            print(f"  private key: stored (fingerprint {fp})")
        if public_entry is not None:
            value, _ = public_entry
            print(f"  public key:  {value.strip()}")
        if config_entry is not None and config_entry[0]:
            lines = config_entry[0].strip().splitlines()
            preview = "; ".join(lines[:3])
            more = "" if len(lines) <= 3 else f" (+{len(lines) - 3} more lines)"
            print(f"  ssh config:  {preview}{more}")
        if known_hosts_entry is not None and known_hosts_entry[0]:
            host_lines = known_hosts_entry[0].strip().splitlines()
            print(f"  known_hosts: {len(host_lines)} entr{'y' if len(host_lines) == 1 else 'ies'}")


def _derive_fingerprint(private_text: str) -> str:
    """Best-effort fingerprint — SHA-256 of the raw key text. Not a real OpenSSH fingerprint
    (which requires extracting the public key), but deterministic and non-reversible."""
    digest = hashlib.sha256(private_text.strip().encode()).hexdigest()
    return f"sha256-tag:{digest[:16]}"
