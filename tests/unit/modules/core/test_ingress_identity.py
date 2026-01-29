"""Tests for IngressIdentity model and DB functions."""
from datetime import datetime
from unittest.mock import MagicMock

from agento.framework.ingress_identity import (
    IngressIdentity,
    bind_identity,
    get_identities_for_agent_view,
    get_ingress_identity,
    list_identities,
    unbind_identity,
)


def _make_row(**overrides):
    base = {
        "id": 1,
        "identity_type": "email",
        "identity_value": "user@example.com",
        "agent_view_id": 10,
        "is_active": 1,
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    base.update(overrides)
    return base


class TestIngressIdentityFromRow:
    def test_from_row_basic(self):
        row = _make_row()
        identity = IngressIdentity.from_row(row)
        assert identity.id == 1
        assert identity.identity_type == "email"
        assert identity.identity_value == "user@example.com"
        assert identity.agent_view_id == 10
        assert identity.is_active is True

    def test_from_row_inactive(self):
        row = _make_row(is_active=0)
        identity = IngressIdentity.from_row(row)
        assert identity.is_active is False

    def test_from_row_different_type(self):
        row = _make_row(identity_type="teams", identity_value="team-channel-id")
        identity = IngressIdentity.from_row(row)
        assert identity.identity_type == "teams"
        assert identity.identity_value == "team-channel-id"


_SENTINEL = object()


def _mock_conn(rows=None, fetchone=_SENTINEL):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    if fetchone is not _SENTINEL:
        cursor.fetchone.return_value = fetchone
    if rows is not None:
        cursor.fetchall.return_value = rows
    return conn, cursor


class TestGetIngressIdentity:
    def test_found(self):
        row = _make_row()
        conn, cursor = _mock_conn(fetchone=row)
        identity = get_ingress_identity(conn, "email", "user@example.com")
        assert identity is not None
        assert identity.identity_type == "email"
        cursor.execute.assert_called_once()

    def test_not_found(self):
        conn, _ = _mock_conn(fetchone=None)
        identity = get_ingress_identity(conn, "email", "nobody@example.com")
        assert identity is None


class TestGetIdentitiesForAgentView:
    def test_returns_list(self):
        rows = [_make_row(id=1), _make_row(id=2, identity_value="other@example.com")]
        conn, _ = _mock_conn(rows=rows)
        identities = get_identities_for_agent_view(conn, 10)
        assert len(identities) == 2
        assert identities[0].id == 1
        assert identities[1].id == 2


class TestBindIdentity:
    def test_bind_calls_execute_and_commit(self):
        conn, cursor = _mock_conn()
        bind_identity(conn, "email", "user@example.com", 10)
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()


class TestUnbindIdentity:
    def test_unbind_deleted(self):
        conn, cursor = _mock_conn()
        cursor.rowcount = 1
        result = unbind_identity(conn, "email", "user@example.com")
        assert result is True
        conn.commit.assert_called_once()

    def test_unbind_not_found(self):
        conn, cursor = _mock_conn()
        cursor.rowcount = 0
        result = unbind_identity(conn, "email", "nobody@example.com")
        assert result is False


class TestListIdentities:
    def test_list_all(self):
        rows = [_make_row(id=1), _make_row(id=2, identity_type="teams")]
        conn, cursor = _mock_conn(rows=rows)
        identities = list_identities(conn)
        assert len(identities) == 2
        # No WHERE clause when no type filter
        sql = cursor.execute.call_args[0][0]
        assert "WHERE" not in sql

    def test_list_filtered_by_type(self):
        rows = [_make_row(id=1)]
        conn, cursor = _mock_conn(rows=rows)
        identities = list_identities(conn, identity_type="email")
        assert len(identities) == 1
        sql = cursor.execute.call_args[0][0]
        assert "WHERE identity_type" in sql
