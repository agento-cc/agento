"""CLI command: outlook:publish — poll each agent_view's mailbox for unread email and publish jobs."""
from __future__ import annotations

import argparse
import logging

from agento.framework.agent_view_runtime import resolve_publish_priority
from agento.framework.config_resolver import ScopedConfigService
from agento.framework.log import get_logger
from agento.framework.scoped_config import Scope
from agento.framework.workspace import get_active_agent_views
from agento.modules.outlook.src.channel import OutlookPublisher
from agento.modules.outlook.src.toolbox_client import OutlookToolboxClient


def _publish_view_messages(publisher, db_config, av, cfg, messages, priority, logger) -> int:
    """Run each message through the publisher's security gate. Per-message errors never abort."""
    published = 0
    for msg in messages:
        message_id = msg.get("id")
        if not message_id:
            continue
        sender = (msg.get("from") or {}).get("address")
        try:
            if publisher.publish_mail(
                db_config, message_id, agent_view_id=av.id, priority=priority,
                sender_email=sender, dmarc=msg.get("dmarc"),
                allowed_senders=cfg.allowed_senders_list, logger=logger,
            ):
                published += 1
        except Exception:
            logger.exception(f"Error publishing outlook message {message_id[:20]}... (view {av.code})")
    return published


def publish_all_views(
    db_config, conn, toolbox_url: str, logger: logging.Logger,
    *, agent_view_code: str | None = None, top_override: int | None = None,
) -> int:
    """Loop active agent_views (id order); poll each view's mailbox and publish to that view.

    The mailbox identifies the agent_view. Iterating in id order makes the lowest-id view win a
    shared mailbox; ``seen_mailboxes`` dedupes the redundant fetch so no duplicate job is created.
    No active agent_views -> clean no-op. Per-view errors log + continue. The toolbox client is
    always closed.
    """
    views = get_active_agent_views(conn)
    if agent_view_code:
        views = [av for av in views if av.code == agent_view_code]

    client = OutlookToolboxClient(toolbox_url)
    publisher = OutlookPublisher()
    seen_mailboxes: set[str] = set()
    published = 0
    try:
        for av in views:
            try:
                cfg = ScopedConfigService(conn, Scope.AGENT_VIEW, av.id).get_module("outlook")
                if cfg is None or not cfg.enabled:
                    logger.debug("Outlook disabled for agent_view %s (id=%d), skipping", av.code, av.id)
                    continue
                top = top_override if top_override else cfg.poll_top
                resp = client.list_unread(top=top, agent_view_id=av.id)
                # Normalize the UPN for dedupe: mailbox addresses are case-insensitive, so the
                # "lowest id wins" guarantee must not depend on casing/whitespace.
                mailbox_key = (resp.get("mailbox") or "").strip().lower()
                if not mailbox_key:
                    logger.warning(
                        "Outlook mailbox unconfigured for agent_view %s (id=%d), skipping", av.code, av.id
                    )
                    continue
                if mailbox_key in seen_mailboxes:
                    logger.warning(
                        "Outlook mailbox %s already handled this run; skipping agent_view %s (id=%d) "
                        "(shared inbox — lowest agent_view id wins)", mailbox_key, av.code, av.id
                    )
                    continue
                seen_mailboxes.add(mailbox_key)
                priority = resolve_publish_priority(conn, av.id)
                published += _publish_view_messages(
                    publisher, db_config, av, cfg, resp.get("messages", []), priority, logger
                )
            except Exception:
                logger.exception(
                    "Outlook publish failed for agent_view %s (id=%d) — continuing with remaining views",
                    av.code, av.id,
                )
                continue
    finally:
        client.close()
    return published


class OutlookPublishCommand:
    @property
    def name(self) -> str:
        return "outlook:publish"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Poll each agent_view's Outlook mailbox and publish unread email as jobs"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--top", type=int, default=None, help="Max unread to fetch per view (<=50); overrides poll_top")
        parser.add_argument("--agent-view", dest="agent_view", default=None,
                            help="Run the loop for one agent_view code only (manual/debug)")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import bootstrap, get_module_config
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection

        logger = get_logger("publisher", "/app/logs/publisher.log", stderr=False)
        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            bootstrap(db_conn=conn)
            outlook_cfg = get_module_config("outlook")
            toolbox_url = getattr(outlook_cfg, "toolbox_url", "") if outlook_cfg else ""
            if not toolbox_url:
                logger.error("core/toolbox/url not set; cannot poll Outlook")
                return
            count = publish_all_views(
                db_config, conn, toolbox_url, logger,
                agent_view_code=args.agent_view, top_override=args.top,
            )
            logger.info(f"Published {count} outlook-mail jobs")
        finally:
            conn.close()
