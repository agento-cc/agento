from __future__ import annotations

import logging

import pymysql

from .models import AgentProvider, Token


def register_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
    label: str,
    credentials_path: str,
    token_limit: int = 0,
    model: str | None = None,
    logger: logging.Logger | None = None,
) -> Token:
    """Register a new token or update credentials if the label already exists."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oauth_token (agent_type, label, credentials_path, token_limit, model)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                credentials_path = VALUES(credentials_path),
                enabled = TRUE,
                updated_at = NOW()
            """,
            (agent_type.value, label, credentials_path, token_limit, model),
        )
        if cur.lastrowid:
            token_id = cur.lastrowid
        else:
            cur.execute("SELECT id FROM oauth_token WHERE label = %s", (label,))
            token_id = cur.fetchone()["id"]
        cur.execute("SELECT * FROM oauth_token WHERE id = %s", (token_id,))
        row = cur.fetchone()
    action = "Registered" if cur.lastrowid else "Updated"
    if logger:
        logger.info(f"{action} token: id={token_id} label={label} model={model}")
    return Token.from_row(row)


def set_primary_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
    token_id: int,
    logger: logging.Logger | None = None,
) -> bool:
    """Set a token as the global primary.

    Clears is_primary on ALL tokens (across all agent types),
    then sets is_primary=TRUE on the target token.
    Only one token can be primary at a time.
    Returns True if the target token was found and updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE oauth_token SET is_primary = FALSE, updated_at = NOW() "
            "WHERE is_primary = TRUE",
        )
        cur.execute(
            "UPDATE oauth_token SET is_primary = TRUE, updated_at = NOW() "
            "WHERE id = %s AND agent_type = %s AND enabled = TRUE",
            (token_id, agent_type.value),
        )
        found = cur.rowcount > 0
    if logger:
        logger.info(f"Set primary token: agent_type={agent_type.value} token_id={token_id} found={found}")
    return found


def deregister_token(
    conn: pymysql.Connection,
    token_id: int,
    logger: logging.Logger | None = None,
) -> bool:
    """Soft-disable a token (sets enabled=FALSE). Returns True if found."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE oauth_token SET enabled = FALSE, updated_at = NOW() WHERE id = %s",
            (token_id,),
        )
        found = cur.rowcount > 0
    if logger:
        logger.info(f"Deregistered token: id={token_id} found={found}")
    return found


def list_tokens(
    conn: pymysql.Connection,
    agent_type: AgentProvider | None = None,
    enabled_only: bool = True,
) -> list[Token]:
    """List tokens, optionally filtered by agent_type and enabled status."""
    sql = "SELECT * FROM oauth_token WHERE 1=1"
    params: list = []
    if agent_type is not None:
        sql += " AND agent_type = %s"
        params.append(agent_type.value)
    if enabled_only:
        sql += " AND enabled = TRUE"
    sql += " ORDER BY id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [Token.from_row(r) for r in rows]


def get_token(
    conn: pymysql.Connection,
    token_id: int,
) -> Token | None:
    """Fetch a single token by ID. Returns None if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM oauth_token WHERE id = %s", (token_id,))
        row = cur.fetchone()
    return Token.from_row(row) if row else None


def get_primary_token(conn: pymysql.Connection) -> Token | None:
    """Return the globally-primary token, or None if none is set."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM oauth_token "
            "WHERE is_primary = TRUE AND enabled = TRUE "
            "LIMIT 1"
        )
        row = cur.fetchone()
    return Token.from_row(row) if row else None


def get_token_by_path(
    conn: pymysql.Connection,
    credentials_path: str,
) -> Token | None:
    """Look up a token by its credentials_path."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM oauth_token WHERE credentials_path = %s",
            (credentials_path,),
        )
        row = cur.fetchone()
    return Token.from_row(row) if row else None
