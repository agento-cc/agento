"""Durable per-mailbox Graph delta cursor store (module-owned, plain SQL on the passed conn).

Stores the full @odata.deltaLink URL Graph returned; the toolbox re-validates it before use.
"""
from __future__ import annotations

import pymysql


def _norm(mailbox: str) -> str:
    return (mailbox or "").strip().lower()


def load_cursors(conn: pymysql.Connection) -> dict[str, str]:
    """Return {normalized_mailbox_upn: delta_link} for every stored cursor."""
    with conn.cursor() as cur:
        cur.execute("SELECT mailbox, delta_link FROM outlook_poll_cursor")
        return {row["mailbox"]: row["delta_link"] for row in cur.fetchall()}


def save_cursor(conn: pymysql.Connection, mailbox: str, delta_link: str) -> None:
    """Upsert the cursor for *mailbox* (normalized) and commit (persist-then-advance)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outlook_poll_cursor (mailbox, delta_link) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE delta_link = VALUES(delta_link)",
            (_norm(mailbox), delta_link),
        )
    conn.commit()
