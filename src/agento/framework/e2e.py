"""End-to-end tests using real LLM calls and the prod database.

Exercises the full consumer pipeline: dequeue → channel → workflow → runner → finalize.
The selected token drives the run; for deterministic targeting the scenario
temporarily disables every other token of the same provider so the LRU pool
has only one candidate, then restores their enabled state at teardown.
Requires healthy tokens and DISABLE_LLM=0.
"""
from __future__ import annotations

import logging
import sys
import time

from .agent_manager.models import Token
from .agent_manager.token_store import get_token, list_tokens, select_token
from .channels.registry import register_channel
from .channels.test import TestChannel
from .consumer import Consumer
from .consumer_config import ConsumerConfig
from .database_config import DatabaseConfig
from .db import get_connection


def _insert_test_job(db_config: DatabaseConfig, reference_id: str) -> int:
    """Insert a TODO job with type/source='blank' and return its id."""
    conn = get_connection(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job (type, source, reference_id,
                                  idempotency_key, status, attempt, max_attempts)
                VALUES ('blank', 'blank', %s, %s, 'TODO', 0, 1)
                """,
                (reference_id, f"e2e:{reference_id}:{int(time.time())}"),
            )
            job_id = cur.lastrowid
        conn.commit()
        return job_id
    finally:
        conn.close()


def _fetch_job(db_config: DatabaseConfig, job_id: int) -> dict | None:
    """Fetch a job row by id."""
    conn = get_connection(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM job WHERE id = %s", (job_id,))
            return cur.fetchone()
    finally:
        conn.close()


def _delete_job(db_config: DatabaseConfig, job_id: int) -> None:
    """Delete a test job row."""
    conn = get_connection(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job WHERE id = %s", (job_id,))
        conn.commit()
    finally:
        conn.close()


def _disable_other_tokens(db_config: DatabaseConfig, token: Token) -> list[int]:
    """Disable every other enabled token of the same agent_type; return their ids."""
    conn = get_connection(db_config)
    try:
        peers = [
            t.id for t in list_tokens(conn, agent_type=token.agent_type)
            if t.id != token.id
        ]
        if peers:
            placeholders = ",".join(["%s"] * len(peers))
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE oauth_token SET enabled = FALSE WHERE id IN ({placeholders})",
                    peers,
                )
            conn.commit()
        return peers
    finally:
        conn.close()


def _restore_tokens(db_config: DatabaseConfig, token_ids: list[int]) -> None:
    """Re-enable tokens previously disabled by ``_disable_other_tokens``."""
    if not token_ids:
        return
    conn = get_connection(db_config)
    try:
        placeholders = ",".join(["%s"] * len(token_ids))
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE oauth_token SET enabled = TRUE WHERE id IN ({placeholders})",
                token_ids,
            )
        conn.commit()
    finally:
        conn.close()


def _run_checks(row: dict) -> list[tuple[str, bool, str]]:
    """Return list of (label, passed, detail) for a finished job row."""
    return [
        ("status=SUCCESS", row["status"] == "SUCCESS", row["status"]),
        ("agent_type set", row["agent_type"] is not None, str(row["agent_type"])),
        ("model set", row["model"] is not None, str(row["model"])),
        ("input_tokens > 0", (row["input_tokens"] or 0) > 0, str(row["input_tokens"])),
        ("prompt saved", bool(row["prompt"]), f"{len(row['prompt'] or '')} chars"),
        ("output saved", bool(row["output"]), f"{len(row['output'] or '')} chars"),
        ("result_summary has stats", "subtype=" in (row["result_summary"] or ""), str(row["result_summary"])),
    ]


def run_scenario(
    token: Token,
    db_config: DatabaseConfig,
    consumer_config: ConsumerConfig,
    logger: logging.Logger,
    *,
    keep: bool = False,
    model: str | None = None,
) -> bool:
    """Run one e2e scenario for the given token. Returns True if all checks pass."""
    description = f"{token.agent_type.value} ({token.label})"
    ref_id = f"E2E-{token.agent_type.value.upper()}-{token.id}"

    print(f"\n{'='*60}")
    print(f"E2E: {description}")
    print(f"{'='*60}")

    register_channel(TestChannel())
    disabled_peers = _disable_other_tokens(db_config, token)

    try:
        job_id = _insert_test_job(db_config, ref_id)
        print(f"  Inserted job id={job_id}, reference_id={ref_id}")

        consumer = Consumer(db_config, consumer_config, logger, model_override=model)
        job = consumer._try_dequeue()
        if job is None:
            print("  FAIL: could not dequeue test job")
            if not keep:
                _delete_job(db_config, job_id)
            return False

        assert job.id == job_id, f"Expected job {job_id}, got {job.id}"
        print(f"  Dequeued job {job.id}, executing...")

        consumer._execute_job(job)

        row = _fetch_job(db_config, job_id)
        if row is None:
            print("  FAIL: job row not found after execution")
            return False

        checks = _run_checks(row)
        all_ok = all(ok for _, ok, _ in checks)

        for label, ok, detail in checks:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {label}: {detail}")

        print(f"\n  Model:  {row['model']}")
        print(f"  Tokens: in={row['input_tokens']} out={row['output_tokens']}")
        output_preview = (row["output"] or "")[:120]
        print(f"  Output: {output_preview}")

        if keep:
            print(f"  Keeping job {job_id} (--keep)")
        else:
            _delete_job(db_config, job_id)
            print(f"  Cleaned up job {job_id}")

        return all_ok
    finally:
        _restore_tokens(db_config, disabled_peers)


def cmd_e2e(args) -> None:
    """CLI entry point for `agent e2e`."""
    from .bootstrap import bootstrap
    from .cli.runtime import _load_framework_config

    db_config, consumer_config, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        bootstrap(db_conn=conn)
    finally:
        conn.close()

    logger = logging.getLogger("e2e")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    conn = get_connection(db_config)
    try:
        if args.oauth_token:
            token = get_token(conn, args.oauth_token)
            if token is None:
                print(f"Token not found: id={args.oauth_token}", file=sys.stderr)
                sys.exit(1)
        else:
            from .agent_manager.models import AgentProvider
            token = None
            for provider in AgentProvider:
                candidate = select_token(conn, provider)
                if candidate is not None:
                    token = candidate
                    break
            if token is None:
                print(
                    "No healthy tokens across any provider. "
                    "Register one: bin/agento token:register <claude|codex> <label>",
                    file=sys.stderr,
                )
                sys.exit(1)
    finally:
        conn.close()

    try:
        ok = run_scenario(token, db_config, consumer_config, logger, keep=args.keep, model=args.model)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        logger.exception(f"E2E failed for token {token.id}")
        ok = False

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {token.agent_type.value} ({token.label})")

    print(f"\n{'ALL PASSED' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)
