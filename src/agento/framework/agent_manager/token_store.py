from __future__ import annotations

import logging

import pymysql

from .models import AgentProvider, Token, encrypt_credentials


def register_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
    label: str,
    credentials: dict,
    token_limit: int = 0,
    model: str | None = None,
    logger: logging.Logger | None = None,
) -> Token:
    """Register (or update) a token. ``credentials`` is a plaintext JSON dict; it
    is encrypted via the framework Encryptor before being stored."""
    encrypted = encrypt_credentials(credentials)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oauth_token (agent_type, label, credentials, token_limit, model)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                credentials = VALUES(credentials),
                enabled = TRUE,
                updated_at = NOW()
            """,
            (agent_type.value, label, encrypted, token_limit, model),
        )
        was_insert = bool(cur.lastrowid)
        if was_insert:
            token_id = cur.lastrowid
        else:
            cur.execute("SELECT id FROM oauth_token WHERE label = %s", (label,))
            token_id = cur.fetchone()["id"]
        cur.execute("SELECT * FROM oauth_token WHERE id = %s", (token_id,))
        row = cur.fetchone()
    action = "Registered" if was_insert else "Updated"
    if logger:
        logger.info(f"{action} token: id={token_id} label={label} model={model}")
    return Token.from_row(row)


def set_primary_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider,
    token_id: int,
    logger: logging.Logger | None = None,
) -> bool:
    """Set a token as the primary for its agent_type.

    Clears ``is_primary`` on every other token for the same agent_type, then
    sets ``is_primary=TRUE`` on the target. Only one token per agent_type is
    primary at a time. Returns True if the target token was found and updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE oauth_token SET is_primary = FALSE, updated_at = NOW() "
            "WHERE agent_type = %s AND is_primary = TRUE",
            (agent_type.value,),
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


def get_primary_token(
    conn: pymysql.Connection,
    agent_type: AgentProvider | None = None,
) -> Token | None:
    """Return the primary enabled token, optionally scoped to an agent_type."""
    sql = "SELECT * FROM oauth_token WHERE is_primary = TRUE AND enabled = TRUE"
    params: list = []
    if agent_type is not None:
        sql += " AND agent_type = %s"
        params.append(agent_type.value)
    sql += " LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return Token.from_row(row) if row else None
