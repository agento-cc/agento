"""Ingress identity model — maps inbound identities to agent_view."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IngressIdentity:
    id: int
    identity_type: str
    identity_value: str
    agent_view_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> IngressIdentity:
        return cls(
            id=row["id"],
            identity_type=row["identity_type"],
            identity_value=row["identity_value"],
            agent_view_id=row["agent_view_id"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def get_ingress_identity(conn, identity_type: str, identity_value: str) -> IngressIdentity | None:
    """Look up an ingress identity by type and value."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM ingress_identity WHERE identity_type = %s AND identity_value = %s",
            (identity_type, identity_value),
        )
        row = cur.fetchone()
    return IngressIdentity.from_row(row) if row else None


def get_identities_for_agent_view(conn, agent_view_id: int) -> list[IngressIdentity]:
    """Get all ingress identities bound to a specific agent_view."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM ingress_identity WHERE agent_view_id = %s ORDER BY identity_type, identity_value",
            (agent_view_id,),
        )
        return [IngressIdentity.from_row(row) for row in cur.fetchall()]


def bind_identity(conn, identity_type: str, identity_value: str, agent_view_id: int) -> None:
    """Bind an inbound identity to an agent_view. Upserts on (type, value)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingress_identity (identity_type, identity_value, agent_view_id, is_active)
            VALUES (%s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE agent_view_id = VALUES(agent_view_id), is_active = 1
            """,
            (identity_type, identity_value, agent_view_id),
        )
    conn.commit()


def unbind_identity(conn, identity_type: str, identity_value: str) -> bool:
    """Remove an ingress identity binding. Returns True if a row was deleted."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ingress_identity WHERE identity_type = %s AND identity_value = %s",
            (identity_type, identity_value),
        )
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted


def list_identities(conn, *, identity_type: str | None = None) -> list[IngressIdentity]:
    """List all ingress identities, optionally filtered by type."""
    query = "SELECT * FROM ingress_identity"
    params: list = []
    if identity_type:
        query += " WHERE identity_type = %s"
        params.append(identity_type)
    query += " ORDER BY identity_type, identity_value"
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [IngressIdentity.from_row(row) for row in cur.fetchall()]
