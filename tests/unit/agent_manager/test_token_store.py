from __future__ import annotations

from unittest.mock import MagicMock

from agento.framework.agent_manager.models import AgentProvider, Token
from agento.framework.agent_manager.token_store import (
    deregister_token,
    get_token,
    get_token_by_path,
    list_tokens,
    register_token,
    set_primary_token,
)


def _mock_conn(fetchone_return=None, fetchall_return=None, lastrowid=1, rowcount=1):
    """Create a mock pymysql Connection with cursor context manager."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    cursor.fetchall.return_value = fetchall_return or []
    cursor.lastrowid = lastrowid
    cursor.rowcount = rowcount
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


_SAMPLE_ROW = {
    "id": 1,
    "agent_type": "claude",
    "label": "prod-1",
    "credentials_path": "/etc/tokens/claude_1.json",
    "model": "claude-sonnet-4-20250514",
    "is_primary": False,
    "token_limit": 100000,
    "enabled": True,
    "created_at": "2025-01-01 00:00:00",
    "updated_at": "2025-01-01 00:00:00",
}


class TestRegisterToken:
    def test_returns_token_from_inserted_row(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW, lastrowid=1)

        token = register_token(
            conn,
            agent_type=AgentProvider.CLAUDE,
            label="prod-1",
            credentials_path="/etc/tokens/claude_1.json",
            token_limit=100000,
        )

        assert isinstance(token, Token)
        assert token.id == 1
        assert token.agent_type == AgentProvider.CLAUDE
        assert token.label == "prod-1"
        assert cursor.execute.call_count == 2  # INSERT + SELECT

    def test_passes_correct_params(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        register_token(conn, AgentProvider.CODEX, "codex-1", "/etc/tokens/codex.json", 50000)

        insert_call = cursor.execute.call_args_list[0]
        assert "INSERT INTO oauth_token" in insert_call[0][0]
        assert insert_call[0][1] == ("codex", "codex-1", "/etc/tokens/codex.json", 50000, None)

    def test_passes_model_param(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        register_token(
            conn, AgentProvider.CLAUDE, "prod-1", "/etc/tokens/claude.json",
            100000, model="claude-sonnet-4-20250514",
        )

        insert_call = cursor.execute.call_args_list[0]
        assert insert_call[0][1] == ("claude", "prod-1", "/etc/tokens/claude.json", 100000, "claude-sonnet-4-20250514")


class TestDeregisterToken:
    def test_returns_true_when_found(self):
        conn, cursor = _mock_conn(rowcount=1)

        result = deregister_token(conn, token_id=5)

        assert result is True
        sql = cursor.execute.call_args[0][0]
        assert "UPDATE oauth_token SET enabled = FALSE" in sql

    def test_returns_false_when_not_found(self):
        conn, _cursor = _mock_conn(rowcount=0)

        result = deregister_token(conn, token_id=999)

        assert result is False


class TestListTokens:
    def test_returns_all_enabled(self):
        conn, cursor = _mock_conn(fetchall_return=[_SAMPLE_ROW, {**_SAMPLE_ROW, "id": 2, "label": "prod-2"}])

        tokens = list_tokens(conn)

        assert len(tokens) == 2
        sql = cursor.execute.call_args[0][0]
        assert "enabled = TRUE" in sql

    def test_filter_by_agent_type(self):
        conn, cursor = _mock_conn(fetchall_return=[_SAMPLE_ROW])

        list_tokens(conn, agent_type=AgentProvider.CLAUDE)

        sql = cursor.execute.call_args[0][0]
        assert "agent_type = %s" in sql
        params = cursor.execute.call_args[0][1]
        assert "claude" in params

    def test_include_disabled(self):
        conn, cursor = _mock_conn(fetchall_return=[])

        list_tokens(conn, enabled_only=False)

        sql = cursor.execute.call_args[0][0]
        assert "enabled = TRUE" not in sql


class TestGetToken:
    def test_returns_token_when_found(self):
        conn, _cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        token = get_token(conn, token_id=1)

        assert token is not None
        assert token.id == 1

    def test_returns_none_when_not_found(self):
        conn, _cursor = _mock_conn(fetchone_return=None)

        token = get_token(conn, token_id=999)

        assert token is None


class TestGetTokenByPath:
    def test_returns_token_when_found(self):
        conn, _cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        token = get_token_by_path(conn, "/etc/tokens/claude_1.json")

        assert token is not None
        assert token.credentials_path == "/etc/tokens/claude_1.json"

    def test_returns_none_when_not_found(self):
        conn, _cursor = _mock_conn(fetchone_return=None)

        token = get_token_by_path(conn, "/nonexistent")

        assert token is None


class TestSetPrimaryToken:
    def test_sets_primary_when_found(self):
        conn, cursor = _mock_conn(rowcount=1)

        result = set_primary_token(conn, AgentProvider.CLAUDE, token_id=1)

        assert result is True
        # Should execute 2 UPDATEs: clear others, set target
        assert cursor.execute.call_count == 2
        clear_sql = cursor.execute.call_args_list[0][0][0]
        assert "is_primary = FALSE" in clear_sql
        set_sql = cursor.execute.call_args_list[1][0][0]
        assert "is_primary = TRUE" in set_sql

    def test_returns_false_when_not_found(self):
        conn, _cursor = _mock_conn(rowcount=0)

        result = set_primary_token(conn, AgentProvider.CLAUDE, token_id=999)

        assert result is False
