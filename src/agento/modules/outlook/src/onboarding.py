from __future__ import annotations

import logging

import pymysql

# Always-required identity/mailbox keys. Auth is satisfied by EITHER a client secret OR a
# certificate path (D-A: support both, selected by config) — checked separately.
_BASE_KEYS = (
    "outlook/outlook_tenant_id",
    "outlook/outlook_client_id",
    "outlook/outlook_mailbox_user_id",
)
_AUTH_KEYS = (
    "outlook/outlook_client_secret",
    "outlook/outlook_cert_path",
)


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
        from agento.framework.core_config import config_set, config_set_auto_encrypt

        print("\n=== Outlook / Microsoft 365 onboarding ===")
        tenant = input("Azure tenant ID: ").strip()
        client_id = input("Azure app (client) ID: ").strip()
        mailbox = input("Mailbox UPN to monitor (e.g. agent@example.com): ").strip()

        auth_choice = terminal.select(
            "Graph authentication method",
            ["Client secret (stored encrypted)", "Certificate (PEM file path)"],
        )
        config_set(conn, "outlook/outlook_tenant_id", tenant)
        config_set(conn, "outlook/outlook_client_id", client_id)
        config_set(conn, "outlook/outlook_mailbox_user_id", mailbox)
        if auth_choice == 0:
            secret = getpass.getpass("Azure app client secret: ").strip()
            config_set_auto_encrypt(conn, "outlook/outlook_client_secret", secret)
        else:
            cert_path = input("Path to certificate PEM (mounted into the toolbox): ").strip()
            config_set(conn, "outlook/outlook_cert_path", cert_path)
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
