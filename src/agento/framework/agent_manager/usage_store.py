from __future__ import annotations

import logging

import pymysql

from .models import UsageSummary


def record_usage(
    conn: pymysql.Connection,
    token_id: int,
    tokens_used: int,
    input_tokens: int,
    output_tokens: int,
    reference_id: str | None = None,
    duration_ms: int = 0,
    model: str | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Insert a usage record. Returns the inserted row ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO usage_log
                (token_id, tokens_used, input_tokens, output_tokens, reference_id, duration_ms, model)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (token_id, tokens_used, input_tokens, output_tokens, reference_id, duration_ms, model),
        )
        row_id = cur.lastrowid
    if logger:
        logger.debug(f"Recorded usage: token_id={token_id} tokens={tokens_used} model={model}")
    return row_id


def get_usage_summary(
    conn: pymysql.Connection,
    token_id: int,
    window_hours: int = 24,
) -> UsageSummary:
    """Aggregate token usage for a single token over a rolling time window."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(tokens_used), 0) AS total_tokens,
                   COUNT(*) AS call_count
            FROM usage_log
            WHERE token_id = %s
              AND created_at >= NOW() - INTERVAL %s HOUR
            """,
            (token_id, window_hours),
        )
        row = cur.fetchone()
    return UsageSummary(
        token_id=token_id,
        total_tokens=row["total_tokens"],
        call_count=row["call_count"],
    )


def get_usage_summaries(
    conn: pymysql.Connection,
    agent_type: str,
    window_hours: int = 24,
) -> list[UsageSummary]:
    """Get usage summaries for all enabled tokens of a given agent type."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id AS token_id,
                   COALESCE(SUM(u.tokens_used), 0) AS total_tokens,
                   COUNT(u.id) AS call_count
            FROM oauth_token t
            LEFT JOIN usage_log u
                   ON u.token_id = t.id
                  AND u.created_at >= NOW() - INTERVAL %s HOUR
            WHERE t.agent_type = %s
              AND t.enabled = TRUE
            GROUP BY t.id
            """,
            (window_hours, agent_type),
        )
        rows = cur.fetchall()
    return [
        UsageSummary(
            token_id=r["token_id"],
            total_tokens=r["total_tokens"],
            call_count=r["call_count"],
        )
        for r in rows
    ]
