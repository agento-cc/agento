"""Integration: auth failure poisons the offending token and the job retries
onto the next healthy token in the LRU pool, dead-lettering only once the pool
is exhausted (real MySQL)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import patch

from agento.framework.agent_manager.errors import AuthenticationError, UsageLimitError
from agento.framework.agent_manager.models import encrypt_credentials
from agento.framework.consumer import Consumer
from agento.framework.runner import RunResult
from agento.modules.claude.src.runner import TokenClaudeRunner
from agento.modules.codex.src.runner import TokenCodexRunner

from .conftest import _test_connection, fetch_job, insert_queued_job, update_job


def _seed_token(label: str, *, priority: int, agent_type: str = "claude") -> int:
    """Insert an enabled, healthy token with an explicit priority. Lower
    priority wins selection (``ORDER BY priority ASC``)."""
    encrypted = encrypt_credentials({"subscription_key": f"sk-invalid-{label}"})
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oauth_token
                    (agent_type, type, label, credentials, enabled, status, priority)
                VALUES (%s, 'oauth', %s, %s, TRUE, 'ok', %s)
                """,
                (agent_type, label, encrypted, priority),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _bind_provider(agent_type: str = "claude") -> None:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO core_config_data (scope, scope_id, path, value, encrypted)
                VALUES ('default', 0, 'agent_view/provider', %s, 0)
                ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = NOW()
                """,
                (agent_type,),
            )
    finally:
        conn.close()


def _token_status(token_id: int) -> str:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM oauth_token WHERE id = %s", (token_id,))
            return cur.fetchone()["status"]
    finally:
        conn.close()


def _token_throttle(token_id: int):
    """Return the token's throttled_until (naive datetime or None)."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT throttled_until FROM oauth_token WHERE id = %s", (token_id,))
            return cur.fetchone()["throttled_until"]
    finally:
        conn.close()


def test_auth_failure_retries_onto_next_healthy_token_then_dead_when_exhausted(
    int_db_config, int_consumer_config,
):
    """Two invalid tokens, A (priority 0) then B (priority 1). Each attempt the
    consumer resolves the lowest-priority healthy token; the runner rejects the
    credential with a 401; the consumer poisons that token and — because a
    healthy alternative still exists — requeues the job. Once both are poisoned
    the pool is exhausted and the job dead-letters."""
    logger = logging.getLogger("test")
    _bind_provider("claude")
    token_a = _seed_token("a", priority=0)
    token_b = _seed_token("b", priority=1)
    job_id = insert_queued_job(
        reference_id="AI-AUTH", idempotency_key="auth-pool:1", max_attempts=3,
    )

    # The runner rejects whatever credential it is handed. token_id is omitted
    # so the consumer attributes the failure to the token IT resolved from the
    # pool (``_handle_auth_failure`` falls back to ``token.id``).
    def _reject(self, *args, **kwargs):
        raise AuthenticationError("401 Unauthorized")

    # Attempt 1: token A selected (priority 0) -> poisoned -> requeue (B healthy).
    with patch.object(TokenClaudeRunner, "run", new=_reject):
        consumer = Consumer(int_db_config, int_consumer_config, logger)
        job = consumer._try_dequeue()
        assert job is not None
        consumer._execute_job(job)

    row = fetch_job(job_id)
    assert row["status"] == "TODO"
    assert row["attempt"] == 1
    assert row["error_class"] == "AuthenticationError"
    assert _token_status(token_a) == "error"
    assert _token_status(token_b) == "ok"

    # Unblock the retry backoff.
    update_job(job_id, scheduled_after="2000-01-01 00:00:00")

    # Attempt 2: token B selected (A poisoned) -> poisoned -> pool exhausted -> DEAD.
    with patch.object(TokenClaudeRunner, "run", new=_reject):
        consumer2 = Consumer(int_db_config, int_consumer_config, logger)
        job2 = consumer2._try_dequeue()
        assert job2 is not None
        assert job2.id == job_id
        consumer2._execute_job(job2)

    row = fetch_job(job_id)
    assert row["status"] == "DEAD"
    assert row["attempt"] == 2
    assert _token_status(token_a) == "error"
    assert _token_status(token_b) == "error"


def _usage_limit_failover(
    db_config, consumer_config, runner_cls, agent_type, success_result, cheap_model,
):
    """Shared body: a usage/session limit on the priority-0 token must THROTTLE it
    (cooldown, not poison) and fail the job over to the healthy priority-1 token,
    which then succeeds. Verified against real MySQL for one provider.

    ``cheap_model`` is threaded through as ``model_override`` (a cheap model per the
    task's cost intent); the runner is mocked so no real API call is made."""
    logger = logging.getLogger("test")
    _bind_provider(agent_type)
    token_a = _seed_token("a", priority=0, agent_type=agent_type)
    token_b = _seed_token("b", priority=1, agent_type=agent_type)
    job_id = insert_queued_job(
        reference_id=f"AI-LIMIT-{agent_type}",
        idempotency_key=f"limit-pool:{agent_type}:1",
        max_attempts=3,
    )

    def _limited(self, *args, **kwargs):
        # No token_id → consumer attributes it to the token it resolved (token A).
        raise UsageLimitError("You've hit your session limit")

    # Attempt 1: token A selected (priority 0) -> usage limit -> throttled -> requeue (B healthy).
    with patch.object(runner_cls, "run", new=_limited):
        consumer = Consumer(db_config, consumer_config, logger, model_override=cheap_model)
        job = consumer._try_dequeue()
        assert job is not None
        consumer._execute_job(job)

    row = fetch_job(job_id)
    assert row["status"] == "TODO"
    assert row["attempt"] == 1
    assert row["error_class"] == "UsageLimitError"
    # Throttled, NOT poisoned: status stays 'ok' and a future throttled_until is set.
    assert _token_status(token_a) == "ok"
    assert _token_throttle(token_a) is not None
    assert _token_throttle(token_a) > datetime.now(UTC).replace(tzinfo=None)
    assert _token_status(token_b) == "ok"
    assert _token_throttle(token_b) is None

    # Unblock the retry backoff.
    update_job(job_id, scheduled_after="2000-01-01 00:00:00")

    # Attempt 2: token A still throttled -> token B selected -> run succeeds -> SUCCESS.
    with patch.object(runner_cls, "run", return_value=success_result):
        consumer2 = Consumer(db_config, consumer_config, logger, model_override=cheap_model)
        job2 = consumer2._try_dequeue()
        assert job2 is not None
        assert job2.id == job_id
        consumer2._execute_job(job2)

    row = fetch_job(job_id)
    assert row["status"] == "SUCCESS"
    assert row["attempt"] == 2
    # A stayed a healthy (throttled) token the whole time; it auto-recovers after cooldown.
    assert _token_status(token_a) == "ok"


def test_claude_usage_limit_throttles_and_fails_over(int_db_config, int_consumer_config):
    success = RunResult(
        raw_output="ok", input_tokens=1500, output_tokens=800, cost_usd=0.01,
        num_turns=1, duration_ms=1000, subtype="success", agent_type="claude",
    )
    _usage_limit_failover(
        int_db_config, int_consumer_config, TokenClaudeRunner, "claude", success,
        cheap_model="claude-haiku-4-5-20251001",
    )


def test_codex_usage_limit_throttles_and_fails_over(int_db_config, int_consumer_config):
    success = RunResult(
        raw_output="ok", input_tokens=1000, output_tokens=None, num_turns=1,
        duration_ms=1000, subtype="success", agent_type="codex",
    )
    _usage_limit_failover(
        int_db_config, int_consumer_config, TokenCodexRunner, "codex", success,
        cheap_model="gpt-5.4-mini",
    )
