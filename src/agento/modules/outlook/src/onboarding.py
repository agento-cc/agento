from __future__ import annotations

import logging

import pymysql

# Always-required identity/mailbox keys. Auth is satisfied by EITHER a client secret OR a
# certificate PEM (its contents, stored encrypted) — support both, selected by config — checked separately.
_BASE_KEYS = (
    "outlook/outlook_tenant_id",
    "outlook/outlook_client_id",
    "outlook/outlook_mailbox_user_id",
)
_AUTH_KEYS = (
    "outlook/outlook_client_secret",
    "outlook/outlook_cert_pem",
)

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


class OutlookOnboarding:
    def describe(self) -> str:
        return "Configure Outlook / Microsoft 365 mailbox connection (Graph app credentials)"

    def is_complete(self, conn: pymysql.connections.Connection) -> bool:
        # Outlook uses ONE GLOBAL mailbox (scope='default', scope_id=0). Unlike jira (per-agent_view),
        # the creds must exist at the default scope specifically.
        all_keys = _BASE_KEYS + _AUTH_KEYS
        placeholders = ",".join(["%s"] * len(all_keys))
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT path FROM core_config_data "
                f"WHERE path IN ({placeholders}) AND scope = 'default' AND scope_id = 0 "
                f"AND value IS NOT NULL AND value <> ''",
                all_keys,
            )
            rows = cur.fetchall()
        found = {row["path"] if isinstance(row, dict) else row[0] for row in rows}
        has_base = set(_BASE_KEYS).issubset(found)
        has_auth = any(k in found for k in _AUTH_KEYS)
        return has_base and has_auth

    def run(self, conn, config: dict, logger: logging.Logger) -> None:
        import getpass

        from agento.framework.cli import terminal
        from agento.framework.core_config import (
            config_delete,
            config_set,
            config_set_auto_encrypt,
        )

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
        config_set(conn, "outlook/outlook_mailbox_user_id", mailbox)
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
            return
        client = OutlookToolboxClient(toolbox_url)
        try:
            client.list_unread(top=1)
            logger.info("Outlook Graph verification OK")
            print(f"  Verified: Graph auth + mailbox '{mailbox}' reachable.")
        except ToolboxAPIError as e:
            print(f"  Error: Graph verification failed ({e}). Check tenant/client/auth/mailbox.")
        except Exception as e:  # toolbox unreachable, network, etc.
            print(f"  Error: Toolbox not reachable at {toolbox_url}: {e}")
        finally:
            client.close()

        # Tools ship DISABLED (opt-in), an allow-list gate AND a route are required — tell the
        # operator the explicit steps before Outlook acts.
        print(
            "\n  Next steps (Outlook tools are opt-in; senders are allow-listed AND routed):\n"
            "    1) Enable the channel tools (one tool_name per `tool:enable` call):\n"
            "       for t in outlook_get_message outlook_reply outlook_mark_processed; do \\\n"
            "         agento tool:enable \"$t\" --agent-view <code>; done\n"
            "    2) Allow-list the authorized sender(s):\n"
            "       agento config:set outlook/allowed_senders \"<sender-address>[,<more>]\"\n"
            "    3) Bind sender(s) to an agent_view BEFORE polling can act:\n"
            "       agento ingress:bind email <sender-address> <agent_view_code>"
        )
