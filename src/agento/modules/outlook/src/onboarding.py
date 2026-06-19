from __future__ import annotations

import logging

import pymysql

# Identity + auth live at the DEFAULT scope (the global Azure app). Auth is satisfied by EITHER a
# client secret OR a certificate PEM (its contents, stored encrypted) — checked separately. The
# mailbox UPN may live at the default scope (single-view) OR an agent_view scope (multi-view), so it
# is checked at ANY scope, not just default.
_IDENTITY_KEYS = (
    "outlook/outlook_tenant_id",
    "outlook/outlook_client_id",
)
_AUTH_KEYS = (
    "outlook/outlook_client_secret",
    "outlook/outlook_cert_pem",
)
_MAILBOX_KEY = "outlook/outlook_mailbox_user_id"

_PEM_END_SENTINEL = "END"


def _read_pem_block(prompt: str) -> str:
    """Read a multi-line pasted PEM from stdin until a lone ``END`` line (or EOF).

    Module-level so it is unit-testable by mocking ``input``.
    """
    print(prompt)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == _PEM_END_SENTINEL:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _pem_has_cert_and_key(pem: str) -> bool:
    """A usable Azure app PEM must contain BOTH a certificate block AND a private-key block.

    Azure's ``ClientCertificatePEMCertificate`` requires both; a cert-only paste otherwise fails
    opaquely at Graph token acquisition. ``PRIVATE KEY-----`` covers PRIVATE KEY / RSA PRIVATE KEY /
    ENCRYPTED PRIVATE KEY.
    """
    return "-----BEGIN CERTIFICATE-----" in pem and "PRIVATE KEY-----" in pem


def _print_next_steps() -> None:
    """Print the operator's post-onboarding checklist (tools opt-in; allow-list; polling opt-in).

    Printed on EVERY onboarding run — including when Graph verification is skipped (no toolbox URL) —
    so the operator always sees the enable steps. Module-level for unit-testability.
    """
    print(
        "\n  Next steps (Outlook tools are opt-in; senders are allow-listed; polling is opt-in):\n"
        "    1) Enable the channel tools (one tool_name per `tool:enable` call):\n"
        "       for t in outlook_get_message outlook_reply outlook_mark_processed; do \\\n"
        "         agento tool:enable \"$t\" --agent-view <code>; done\n"
        "    2) Allow-list the authorized sender(s) (per-view: add --scope agent_view --scope-id <id>):\n"
        "       agento config:set outlook/allowed_senders \"<sender-address>[,<more>]\"\n"
        "    3) Enable polling for the mailbox's scope (default is off, so the publisher skips it):\n"
        "       agento config:set outlook/enabled 1   # per-view: add --scope agent_view --scope-id <id>"
    )


class OutlookOnboarding:
    def describe(self) -> str:
        return "Configure Outlook / Microsoft 365 mailbox connection (Graph app credentials)"

    def is_complete(self, conn: pymysql.connections.Connection) -> bool:
        # Identity + auth (the global Azure app) must exist at the DEFAULT scope. The mailbox UPN may
        # live at ANY scope: default (single-view) or agent_view (multi-view).
        default_keys = _IDENTITY_KEYS + _AUTH_KEYS
        placeholders = ",".join(["%s"] * len(default_keys))
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT path FROM core_config_data "
                f"WHERE path IN ({placeholders}) AND scope = 'default' AND scope_id = 0 "
                f"AND value IS NOT NULL AND value <> ''",
                default_keys,
            )
            found = {row["path"] if isinstance(row, dict) else row[0] for row in cur.fetchall()}
            has_identity = set(_IDENTITY_KEYS).issubset(found)
            has_auth = any(k in found for k in _AUTH_KEYS)
            cur.execute(
                "SELECT 1 FROM core_config_data "
                "WHERE path = %s AND value IS NOT NULL AND value <> '' LIMIT 1",
                (_MAILBOX_KEY,),
            )
            has_mailbox = cur.fetchone() is not None
        return has_identity and has_auth and has_mailbox

    def run(self, conn, config: dict, logger: logging.Logger) -> None:
        import getpass

        from agento.framework.cli import terminal
        from agento.framework.core_config import (
            config_delete,
            config_set,
            config_set_auto_encrypt,
        )
        from agento.framework.scoped_config import Scope, scoped_config_set
        from agento.framework.workspace import get_active_agent_views

        print("\n=== Outlook / Microsoft 365 onboarding ===")
        tenant = input("Azure tenant ID: ").strip()
        client_id = input("Azure app (client) ID: ").strip()
        mailbox = input("Mailbox UPN to monitor (e.g. agent@example.com): ").strip()

        auth_choice = terminal.select(
            "Graph authentication method",
            ["Client secret (stored encrypted)", "Certificate (paste PEM contents)"],
        )
        config_set(conn, "outlook/outlook_tenant_id", tenant)
        config_set(conn, "outlook/outlook_client_id", client_id)
        # All credential writes AND the stale-branch deletes below run in the SAME transaction as the
        # single conn.commit() at the end — never after it. The Graph verification reads config via the
        # toolbox's own DB connection (committed rows only); deleting after the commit would let stale
        # cert material survive (graph-auth gives the certificate precedence when both are present).
        if auth_choice == 0:
            secret = getpass.getpass("Azure app client secret: ").strip()
            config_set_auto_encrypt(conn, "outlook/outlook_client_secret", secret)
            # Switched to secret auth: drop any stale certificate material (+ legacy path).
            config_delete(conn, "outlook/outlook_cert_pem")
            config_delete(conn, "outlook/outlook_cert_password")
            config_delete(conn, "outlook/outlook_cert_path")
        else:
            pem = ""
            while True:
                pem = _read_pem_block(
                    "Paste the certificate PEM (cert + private key), then a line with just END:"
                )
                if not pem:
                    print("  Aborted: no PEM provided (nothing saved).")
                    return
                if _pem_has_cert_and_key(pem):
                    break
                print(
                    "  Error: the PEM must contain BOTH a certificate block and a private-key block. "
                    "Paste the full PEM (cert + key) again."
                )
            # NOTE: do NOT .strip() the passphrase — surrounding whitespace can be significant. Only an
            # exactly-empty string means "no passphrase".
            cert_password = getpass.getpass(
                "Certificate PEM passphrase (leave empty if unencrypted): "
            )
            config_set_auto_encrypt(conn, "outlook/outlook_cert_pem", pem)
            if cert_password != "":
                config_set_auto_encrypt(conn, "outlook/outlook_cert_password", cert_password)
            else:
                config_delete(conn, "outlook/outlook_cert_password")
            # Switched to certificate auth: drop any stale client secret (+ legacy path).
            config_delete(conn, "outlook/outlook_client_secret")
            config_delete(conn, "outlook/outlook_cert_path")

        # Mailbox: the mailbox identifies the agent_view. One mailbox per onboarding run.
        verify_agent_view_id: int | None = None
        views = get_active_agent_views(conn)
        if len(views) > 1:
            idx = terminal.select(
                "Which agent_view owns this mailbox?", [av.code for av in views]
            )
            av = views[idx]
            scoped_config_set(
                conn, _MAILBOX_KEY, mailbox,
                scope=Scope.AGENT_VIEW, scope_id=av.id, encrypted=False,
            )
            verify_agent_view_id = av.id
            print(f"  Mailbox '{mailbox}' bound to agent_view '{av.code}'.")
        else:
            # 0 or 1 active view -> default scope (a single view resolves it via fallback).
            config_set(conn, _MAILBOX_KEY, mailbox)
        conn.commit()

        # Verify Graph auth + mailbox access NOW (the toolbox reads the just-committed config per
        # request and decrypts the obscure secret, so /api/outlook/unread exercises the real creds).
        from agento.framework.bootstrap import get_module_config
        from agento.modules.outlook.src.toolbox_client import (
            OutlookToolboxClient,
            ToolboxAPIError,
        )

        core_cfg = get_module_config("core")
        toolbox_url = core_cfg.get("toolbox/url", "") if isinstance(core_cfg, dict) else ""
        if not toolbox_url:
            print("  Saved, but core/toolbox/url is not set — cannot verify now. "
                  "Set it, then run `agento outlook:publish --top 1`.")
            _print_next_steps()
            return
        client = OutlookToolboxClient(toolbox_url)
        try:
            client.list_unread(top=1, agent_view_id=verify_agent_view_id)
            logger.info("Outlook Graph verification OK")
            print(f"  Verified: Graph auth + mailbox '{mailbox}' reachable.")
        except ToolboxAPIError as e:
            print(f"  Error: Graph verification failed ({e}). Check tenant/client/auth/mailbox.")
        except Exception as e:  # toolbox unreachable, network, etc.
            print(f"  Error: Toolbox not reachable at {toolbox_url}: {e}")
        finally:
            client.close()

        # Tools ship DISABLED (opt-in), an allow-list gate is required, and polling is opt-in — tell
        # the operator the explicit steps before Outlook acts.
        _print_next_steps()
