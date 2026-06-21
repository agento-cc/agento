"""CLI command: outlook:publish — poll each agent_view's mailbox (Graph delta cursor) for new email and publish jobs."""
from __future__ import annotations

import argparse
import logging

from agento.framework.agent_view_runtime import resolve_publish_priority
from agento.framework.config_resolver import ScopedConfigService
from agento.framework.log import get_logger
from agento.framework.scoped_config import Scope
from agento.framework.workspace import get_active_agent_views
from agento.modules.outlook.src.channel import OutlookPublisher
from agento.modules.outlook.src.cursor import load_cursors, save_cursor
from agento.modules.outlook.src.toolbox_client import OutlookToolboxClient


def _publish_view_messages(publisher, db_config, av, cfg, messages, priority, logger):
    """Gate+publish each message. Returns (published_count, hold). hold=True means a genuinely
    TRANSIENT condition (a publish exception, e.g. a DB blip) was seen → caller must NOT advance the
    cursor so the batch is re-fetched next poll. Per-message errors never abort the batch.

    A non-pass DMARC verdict — including ``temperror`` — must NOT hold. The verdict is read from the
    immutable receipt-time Authentication-Results header (parseDmarcVerdict), so it never changes on
    re-fetch; holding on it would pin the cursor forever (re-fetch grows without bound — the exact
    bounded-load regression DECISIONS.md resolves against). Such mail simply advances unpublished
    (re-evaluable only via a deliberate cursor resync)."""
    published = 0
    hold = False
    for msg in messages:
        message_id = msg.get("id")
        if not message_id:
            continue
        sender = (msg.get("from") or {}).get("address")
        try:
            if publisher.publish_mail(
                db_config, message_id, agent_view_id=av.id, priority=priority,
                sender_email=sender, dmarc=msg.get("dmarc"),
                allowed_senders=cfg.allowed_senders_list,
                subject=msg.get("subject"), logger=logger,
            ):
                published += 1
        except Exception:
            logger.exception(f"Error publishing outlook message {message_id[:20]}... (view {av.code})")
            hold = True  # transient publish failure (e.g. DB blip) — do not advance past it
    return published, hold


def publish_all_views(
    db_config, conn, toolbox_url: str, logger: logging.Logger,
    *, agent_view_code: str | None = None, top_override: int | None = None,
) -> int:
    """Loop active agent_views (id order); poll each view's mailbox via the Graph delta cursor and
    publish to that view.

    Poll progress is tracked by a durable per-mailbox ``@odata.deltaLink`` (NOT ``isRead``), so
    rejected/in-flight unread mail can't clog the window. The mailbox identifies the agent_view;
    iterating in id order makes the lowest-id view win a shared mailbox, and ``seen_mailboxes``
    dedupes the redundant fetch so no duplicate job is created. Persist-then-advance: the cursor is
    written only AFTER a clean publish pass (and never when a transient hold occurred). The mailbox
    is never mutated. No active agent_views -> clean no-op. Per-view errors log + continue. The
    toolbox client is always closed.
    """
    views = get_active_agent_views(conn)
    if agent_view_code:
        views = [av for av in views if av.code == agent_view_code]

    client = OutlookToolboxClient(toolbox_url)
    publisher = OutlookPublisher()
    cursors = load_cursors(conn)
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
                resp = client.list_delta(top=top, agent_view_id=av.id, cursors=cursors)
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
                pub_count, hold = _publish_view_messages(
                    publisher, db_config, av, cfg, resp.get("messages", []), priority, logger
                )
                published += pub_count
                # PERSIST-THEN-ADVANCE: only after publishing, and only when the batch had no transient
                # condition. A held / errored cursor is re-fetched on the next poll.
                new_link = resp.get("deltaLink")
                if new_link and not hold:
                    save_cursor(conn, mailbox_key, new_link)
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
        return "Poll each agent_view's Outlook mailbox (Graph delta cursor) and publish new email as jobs"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--top", type=int, default=None,
                            help="Delta page size per view (<=50); overrides poll_top (the poll still pages to the end)")
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
