from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agento.framework.agent_manager.models import AgentProvider, Token, TokenStatus
from agento.framework.agent_manager.token_store import (
    clear_token_error,
    count_tokens_for_provider,
    deregister_token,
    get_token,
    list_tokens,
    mark_token_error,
    register_token,
    select_token,
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


def _mock_conn_with_fetches(fetchone_seq, fetchone_seq_scalar=None):
    """Mock connection where fetchone returns successive values from a sequence."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone_seq
    cursor.lastrowid = 1
    cursor.rowcount = 1
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


_ENCRYPTED_BLOB = "aes256:deadbeef:cafebabe"
_PLAINTEXT_CREDS = {"subscription_key": "sk-test"}

_SAMPLE_ROW = {
    "id": 1,
    "agent_type": "claude",
    "label": "prod-1",
    "credentials": _ENCRYPTED_BLOB,
    "model": "claude-sonnet-4-20250514",
    "token_limit": 100000,
    "enabled": True,
    "status": "ok",
    "error_msg": None,
    "expires_at": None,
    "used_at": None,
    "created_at": "2025-01-01 00:00:00",
    "updated_at": "2025-01-01 00:00:00",
}


class _FakeEncryptor:
    def encrypt(self, plaintext: str) -> str:
        return f"aes256:iv:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        import json
        if ciphertext == _ENCRYPTED_BLOB:
            return json.dumps(_PLAINTEXT_CREDS)
        return ciphertext.split(":", 2)[-1]


@pytest.fixture(autouse=True)
def _fake_encryptor(monkeypatch):
    from agento.framework import encryptor as enc
    monkeypatch.setattr(enc, "_instance", _FakeEncryptor())
    yield


class TestRegisterToken:
    def test_returns_token_from_inserted_row(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW, lastrowid=1)

        token = register_token(
            conn,
            agent_type=AgentProvider.CLAUDE,
            label="prod-1",
            credentials=_PLAINTEXT_CREDS,
            token_limit=100000,
        )

        assert isinstance(token, Token)
        assert token.id == 1
        assert token.agent_type == AgentProvider.CLAUDE
        assert token.label == "prod-1"
        assert token.credentials == _PLAINTEXT_CREDS
        assert cursor.execute.call_count == 2  # INSERT + SELECT

    def test_passes_encrypted_credentials(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        register_token(conn, AgentProvider.CODEX, "codex-1", _PLAINTEXT_CREDS, 50000)

        insert_call = cursor.execute.call_args_list[0]
        assert "INSERT INTO oauth_token" in insert_call[0][0]
        assert "credentials" in insert_call[0][0]
        params = insert_call[0][1]
        assert params[0] == "codex"
        assert params[1] == "codex-1"
        assert params[2].startswith("aes256:")
        assert params[3] == 50000

    def test_register_resets_status_and_clears_error_on_refresh(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        register_token(conn, AgentProvider.CLAUDE, "prod-1", _PLAINTEXT_CREDS)

        insert_sql = cursor.execute.call_args_list[0][0][0]
        assert "status = 'ok'" in insert_sql
        assert "error_msg = NULL" in insert_sql

    def test_pulls_expires_at_from_credentials_epoch(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        creds = {"subscription_key": "sk-test", "expires_at": 1893456000}
        register_token(conn, AgentProvider.CLAUDE, "prod-1", creds)

        params = cursor.execute.call_args_list[0][0][1]
        assert params[-1] == datetime(2030, 1, 1, 0, 0, 0)

    def test_pulls_expires_at_from_credentials_iso(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        creds = {"subscription_key": "sk-test", "expires_at": "2030-06-01T12:34:56Z"}
        register_token(conn, AgentProvider.CLAUDE, "prod-1", creds)

        params = cursor.execute.call_args_list[0][0][1]
        assert params[-1] == datetime(2030, 6, 1, 12, 34, 56)

    def test_malformed_expires_at_becomes_null(self):
        conn, cursor = _mock_conn(fetchone_return=_SAMPLE_ROW)

        creds = {"subscription_key": "sk-test", "expires_at": "not-a-date"}
        register_token(conn, AgentProvider.CLAUDE, "prod-1", creds)

        params = cursor.execute.call_args_list[0][0][1]
        assert params[-1] is None


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
        conn, cursor = _mock_conn(
            fetchall_return=[_SAMPLE_ROW, {**_SAMPLE_ROW, "id": 2, "label": "prod-2"}],
        )

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


class TestSelectToken:
    def test_selects_lru_healthy_and_stamps_used_at(self):
        conn, cursor = _mock_conn_with_fetches(
            [{"id": 1}, _SAMPLE_ROW],
        )

        token = select_token(conn, AgentProvider.CLAUDE)

        assert token is not None
        assert token.id == 1
        assert cursor.execute.call_count == 3
        select_sql = cursor.execute.call_args_list[0][0][0]
        assert "FOR UPDATE SKIP LOCKED" in select_sql
        assert "status = 'ok'" in select_sql
        assert "expires_at IS NULL OR expires_at > UTC_TIMESTAMP()" in select_sql
        update_sql = cursor.execute.call_args_list[1][0][0]
        assert "SET used_at = UTC_TIMESTAMP()" in update_sql
        conn.commit.assert_called()

    def test_returns_none_when_no_healthy_token(self):
        conn, _cursor = _mock_conn(fetchone_return=None)

        token = select_token(conn, AgentProvider.CODEX)

        assert token is None
        conn.commit.assert_called()

    def test_orders_nulls_first(self):
        conn, _cursor = _mock_conn_with_fetches([{"id": 1}, _SAMPLE_ROW])

        select_token(conn, AgentProvider.CLAUDE)

        select_sql = _cursor.execute.call_args_list[0][0][0]
        assert "ORDER BY used_at IS NULL DESC" in select_sql

    def test_filters_by_agent_type(self):
        conn, cursor = _mock_conn_with_fetches([{"id": 1}, _SAMPLE_ROW])

        select_token(conn, AgentProvider.CODEX)

        params = cursor.execute.call_args_list[0][0][1]
        assert params == ("codex",)


class TestMarkAndClearTokenError:
    def test_mark_token_error_sets_status_and_msg(self):
        conn, cursor = _mock_conn(rowcount=1)

        result = mark_token_error(conn, 7, "OAuth expired")

        assert result is True
        sql = cursor.execute.call_args[0][0]
        assert "status = 'error'" in sql
        params = cursor.execute.call_args[0][1]
        assert params == ("OAuth expired", 7)

    def test_mark_token_error_truncates_long_message(self):
        conn, cursor = _mock_conn(rowcount=1)

        mark_token_error(conn, 7, "x" * 5000)

        params = cursor.execute.call_args[0][1]
        assert len(params[0]) == 1000

    def test_mark_token_error_returns_false_when_not_found(self):
        conn, _cursor = _mock_conn(rowcount=0)

        assert mark_token_error(conn, 999, "msg") is False

    def test_clear_token_error_resets_status(self):
        conn, cursor = _mock_conn(rowcount=1)

        result = clear_token_error(conn, 7)

        assert result is True
        sql = cursor.execute.call_args[0][0]
        assert "status = 'ok'" in sql
        assert "error_msg = NULL" in sql

    def test_clear_token_error_returns_false_when_not_found(self):
        conn, _cursor = _mock_conn(rowcount=0)

        assert clear_token_error(conn, 999) is False


class TestCountTokensForProvider:
    def test_returns_total_and_healthy(self):
        conn, cursor = _mock_conn_with_fetches([{"c": 3}, {"c": 1}])

        total, healthy = count_tokens_for_provider(conn, AgentProvider.CLAUDE)

        assert total == 3
        assert healthy == 1
        assert cursor.execute.call_count == 2
        healthy_sql = cursor.execute.call_args_list[1][0][0]
        assert "status = 'ok'" in healthy_sql
        assert "expires_at IS NULL OR expires_at > UTC_TIMESTAMP()" in healthy_sql

    def test_zero_when_no_tokens(self):
        conn, _cursor = _mock_conn_with_fetches([{"c": 0}, {"c": 0}])

        total, healthy = count_tokens_for_provider(conn, AgentProvider.CODEX)

        assert total == 0
        assert healthy == 0


class TestTokenStatusMapping:
    def test_from_row_with_ok(self):
        conn, _cursor = _mock_conn(fetchone_return={**_SAMPLE_ROW, "status": "ok"})
        token = get_token(conn, 1)
        assert token.status == TokenStatus.OK

    def test_from_row_with_error(self):
        conn, _cursor = _mock_conn(
            fetchone_return={**_SAMPLE_ROW, "status": "error", "error_msg": "expired"},
        )
        token = get_token(conn, 1)
        assert token.status == TokenStatus.ERROR
        assert token.error_msg == "expired"
