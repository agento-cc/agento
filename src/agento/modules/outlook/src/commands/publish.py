"""CLI command: outlook:publish — poll the mailbox for unread email and publish jobs."""
from __future__ import annotations

import argparse
import logging

from agento.framework.log import get_logger
from agento.modules.outlook.src.channel import OutlookPublisher
from agento.modules.outlook.src.toolbox_client import OutlookToolboxClient


def publish_mail(
    db_config, toolbox_url: str, top: int,
    allowed_senders: list[str], require_dmarc: bool,
    logger: logging.Logger,
) -> int:
    """Fetch unread messages and publish each as a TODO job. Returns count published.

    Each message is run through the publisher's security gate (allowed_senders + DMARC), so a
    per-message failure must not abort the loop and the toolbox client is always closed.
    """
    client = OutlookToolboxClient(toolbox_url)
    publisher = OutlookPublisher()
    published = 0
    try:
        messages = client.list_unread(top=top)
        for msg in messages:
            message_id = msg.get("id")
            if not message_id:
                continue
            sender = (msg.get("from") or {}).get("address")
            dmarc = msg.get("dmarc")
            try:
                if publisher.publish_mail(
                    db_config, message_id, sender_email=sender, dmarc=dmarc,
                    allowed_senders=allowed_senders, require_dmarc=require_dmarc, logger=logger,
                ):
                    published += 1
            except Exception:
                logger.exception(f"Error publishing outlook message {message_id[:20]}...")
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
        return "Poll the Outlook mailbox and publish unread email as jobs"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--top", type=int, default=None, help="Max unread to fetch (<=50)")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import bootstrap, get_module_config
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection

        logger = get_logger("publisher", "/app/logs/publisher.log", stderr=False)
        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            bootstrap(db_conn=conn)
        finally:
            conn.close()

        # get_module_config("outlook") returns an OutlookConfig DATACLASS (not a dict): bootstrap
        # converts the resolved dict via config_class.from_dict because di.json declares config_class.
        # Use attribute access — dict .get() would raise AttributeError on the dataclass.
        outlook_cfg = get_module_config("outlook")
        if outlook_cfg is None or not getattr(outlook_cfg, "enabled", False):
            logger.debug("Outlook disabled, skipping publish")
            return
        toolbox_url = outlook_cfg.toolbox_url
        top = args.top or int(getattr(outlook_cfg, "poll_top", 10) or 10)

        count = publish_mail(
            db_config, toolbox_url, top,
            outlook_cfg.allowed_senders_list, outlook_cfg.require_dmarc, logger,
        )
        logger.info(f"Published {count} outlook-mail jobs")
