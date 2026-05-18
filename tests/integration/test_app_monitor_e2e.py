"""Full end-to-end coverage for the ``app_monitor`` verification gate.

These tests drive the real ``Consumer`` against the integration MySQL DB with
a patched runner that:

- Reports rc=0 success (``RunResult`` with ``subtype=<uuid>`` as the
  session_id and ``agent_type`` set to the provider name).
- Writes a deterministic transcript JSONL at the per-provider production
  layout under the consumer-resolved ``home_dir`` (a real per-agent_view
  build dir under the patched ``BUILD_DIR``).
- Triggers the runner's ``session_id_callback`` so the consumer persists the
  session_id on the job row before ``_finalize_job`` dispatches
  ``job_finalize_before``.

The verification observer then resolves the per-provider ``TranscriptReader``
via the framework registry, parses the synthesized transcript, and emits a
``Verdict`` based on its contents (zero ``mcp__toolbox__*`` calls,
unrecognized format, or a clean run with at least one toolbox call).

The cases prove:

1. claude no-MCP → first attempt re-queued with ``session_id`` cleared.
2. claude no-MCP exhausting ``max_attempts`` → DEAD + email sent.
3. claude with MCP calls → SUCCESS (control case — no false positives).
4. codex no-MCP → same end-state via the *Codex* transcript reader
   (agent-agnostic proof point).
5. unknown provider (e.g. ``hermes``) → trust rc=0 → SUCCESS + no email.
6. claude format drift (10 JSON records, none recognized) → DEAD on first
   attempt with ``transcript_parse_failed`` verdict and parser-specific
   email body.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.consumer import Consumer
from agento.modules.app_monitor.src import observers as obs
from agento.modules.app_monitor.src.constants import (
    CFG_ALERT_EMAIL_TO,
    CFG_ALERT_SMTP_FROM,
    CFG_ALERT_SMTP_HOST,
    CFG_ALERT_SMTP_PORT,
    CFG_ALERT_SMTP_TLS,
    CFG_MISSING_TRANSCRIPT_POLICY,
    POLICY_DEAD,
)
from agento.modules.claude.src.output_parser import ClaudeResult

from .conftest import (
    _test_connection,
    fetch_job,
    insert_primary_token,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"
CODEX_FIXTURES = FIXTURES / "codex"


# --- DB helpers ---------------------------------------------------------------


def _insert_workspace(code: str = "acme") -> int:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace (code, label) VALUES (%s, %s)",
                (code, code),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _insert_agent_view(workspace_id: int, code: str = "developer") -> int:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                (workspace_id, code, code),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _insert_job_with_agent_view(
    agent_view_id: int,
    *,
    reference_id: str = "AI-1",
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> int:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job (type, source, agent_view_id, reference_id,
                                    idempotency_key, status, attempt, max_attempts)
                   VALUES ('cron', 'jira', %s, %s, %s, 'TODO', 0, %s)""",
                (agent_view_id, reference_id,
                 idempotency_key or f"test:app_monitor_e2e:{reference_id}",
                 max_attempts),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _cleanup_test_data() -> None:
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            cur.execute(
                "DELETE FROM core_config_data "
                "WHERE scope IN ('workspace','agent_view') OR path = 'agent_view/provider'"
            )
            cur.execute("DELETE FROM workspace_build")
            cur.execute("DELETE FROM job")
            cur.execute("DELETE FROM agent_view")
            cur.execute("DELETE FROM workspace")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    finally:
        conn.close()


def _force_immediate_redeque(job_id: int) -> None:
    """Rewind ``scheduled_after`` so the next dequeue picks the job up
    immediately, regardless of the configured retry backoff."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job SET scheduled_after = NOW() - INTERVAL 1 SECOND "
                "WHERE id = %s",
                (job_id,),
            )
    finally:
        conn.close()


# --- runner callbacks: produce rc=0 + write a transcript ---------------------


def _claude_callback(
    transcript_payload: str,
    *,
    captured: list[str] | None = None,
):
    """Build a ``TokenClaudeRunner.run`` replacement that writes the given
    transcript content to the production layout under
    ``<home_dir>/.claude/projects/<X>/<session_id>.jsonl``, fires the
    session_id callback, and returns a successful ``ClaudeResult``.
    """
    def _run(self_runner, prompt, *, model=None):
        home = Path(self_runner.home_dir)
        sid = str(uuid.uuid4())
        if captured is not None:
            captured.append(sid)
        proj = home / ".claude" / "projects" / "-workspace-test"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / f"{sid}.jsonl").write_text(transcript_payload)
        if self_runner.session_id_callback:
            self_runner.session_id_callback(sid)
        return ClaudeResult(
            raw_output="ok",
            input_tokens=100, output_tokens=50,
            duration_ms=1000,
            subtype=sid,
            agent_type="claude",
        )
    return _run


def _codex_callback(
    transcript_payload: str,
    *,
    captured: list[str] | None = None,
):
    """Build a ``TokenCodexRunner.run`` replacement that writes the given
    transcript content to ``<home_dir>/.codex/sessions/2026/05/14/rollout-...-<sid>.jsonl``.
    """
    def _run(self_runner, prompt, *, model=None):
        home = Path(self_runner.home_dir)
        sid = str(uuid.uuid4())
        if captured is not None:
            captured.append(sid)
        sessions = home / ".codex" / "sessions" / "2026" / "05" / "14"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"rollout-2026-05-14T05-05-33-{sid}.jsonl").write_text(transcript_payload)
        if self_runner.session_id_callback:
            self_runner.session_id_callback(sid)
        return ClaudeResult(
            raw_output="ok",
            input_tokens=100, output_tokens=50,
            duration_ms=1000,
            subtype=sid,
            agent_type="codex",
            model="o3",
        )
    return _run


def _hermes_callback(self_runner, prompt, *, model=None):
    """Claude runner patched to report ``agent_type="hermes"`` — a provider
    with no registered ``TranscriptReader``. Writes no transcript."""
    sid = str(uuid.uuid4())
    if self_runner.session_id_callback:
        self_runner.session_id_callback(sid)
    return ClaudeResult(
        raw_output="ok",
        input_tokens=10, output_tokens=5,
        duration_ms=100,
        subtype=sid,
        agent_type="hermes",
    )


# --- common fixtures ---------------------------------------------------------


def _patch_app_monitor(monkeypatch) -> MagicMock:
    """Override the session-wide ``policy=trust`` set in conftest, configure
    email alerts, and intercept ``send_alert``. Reverts automatically at
    test teardown."""
    monkeypatch.setattr(obs, "_config", lambda: {
        CFG_MISSING_TRANSCRIPT_POLICY: POLICY_DEAD,
        CFG_ALERT_EMAIL_TO: "ops@example.com",
        CFG_ALERT_SMTP_HOST: "smtp.example.com",
        CFG_ALERT_SMTP_FROM: "agento@example.com",
        CFG_ALERT_SMTP_PORT: 587,
        CFG_ALERT_SMTP_TLS: False,
    })
    sender = MagicMock()
    monkeypatch.setattr(obs, "send_alert", sender)
    return sender


def _enter_build_dir_patches(stack: ExitStack, build_root: Path) -> None:
    """Patch every module-level ``BUILD_DIR`` / ``ARTIFACTS_DIR`` reference so
    the consumer + readers + workspace_build all agree on ``tmp_path``. Keep
    this list in sync with new readers / observers."""
    artifacts_root = str(build_root.parent / "artifacts")
    build_str = str(build_root)
    stack.enter_context(patch("agento.framework.artifacts_dir.ARTIFACTS_DIR", artifacts_root))
    stack.enter_context(patch("agento.framework.artifacts_dir.BUILD_DIR", build_str))
    stack.enter_context(patch("agento.modules.workspace_build.src.builder.BUILD_DIR", build_str))
    stack.enter_context(patch("agento.modules.claude.src.transcript_reader.BUILD_DIR", build_str))
    stack.enter_context(patch("agento.modules.codex.src.transcript_reader.BUILD_DIR", build_str))


# --- the suite ---------------------------------------------------------------


class TestAppMonitorE2E:
    """End-to-end coverage for the verification gate against real MySQL."""

    @pytest.fixture(autouse=True)
    def _patch_observer_db(self, int_db_config):
        """Make observers see the integration test DB (mirrors the recipe in
        ``tests/integration/test_instruction_files.py``).

        ``app_monitor.observers`` is here too because ``_save_toolbox_mcp_calls``
        opens its own connection via ``DatabaseConfig.from_env()``.
        """
        with patch(
            "agento.modules.agent_view.src.observers.DatabaseConfig.from_env",
            return_value=int_db_config,
        ), patch(
            "agento.modules.workspace_build.src.observers.DatabaseConfig.from_env",
            return_value=int_db_config,
        ), patch(
            "agento.modules.app_monitor.src.observers.DatabaseConfig.from_env",
            return_value=int_db_config,
        ):
            yield

    def setup_method(self):
        _cleanup_test_data()

    def teardown_method(self):
        _cleanup_test_data()

    # -- happy + sad paths for Claude --------------------------------------

    def test_claude_no_mcp_first_attempt_retries_with_fresh_session(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch,
    ):
        sender = _patch_app_monitor(monkeypatch)
        insert_primary_token("claude")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=2, reference_id="AI-101")

        captured: list[str] = []
        payload = (FIXTURES / "bad_no_mcp.jsonl").read_text()
        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.claude.src.runner.TokenClaudeRunner.run",
                _claude_callback(payload, captured=captured),
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            job = consumer._try_dequeue()
            assert job is not None
            consumer._execute_job(job)

        row = fetch_job(job_id)
        assert row["status"] == "TODO", row
        assert row["attempt"] == 1
        # fresh_start=True → session_id cleared so the next attempt starts a
        # brand-new agent session (the fix for the resume-loop incident).
        assert row["session_id"] is None
        assert row["error_class"] == "JobVerificationFailed"
        assert "no_mcp_calls" in (row["error_message"] or "")
        # Parse succeeded, zero toolbox calls observed → column = 0 (not NULL).
        assert row["toolbox_mcp_calls"] == 0
        # No DEAD yet → email observer must not have fired.
        sender.assert_not_called()
        assert len(captured) == 1

    def test_claude_no_mcp_exhausts_retries_then_dead_letters_with_email(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch,
    ):
        sender = _patch_app_monitor(monkeypatch)
        insert_primary_token("claude")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=2, reference_id="AI-102")

        payload = (FIXTURES / "bad_no_mcp.jsonl").read_text()
        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.claude.src.runner.TokenClaudeRunner.run",
                _claude_callback(payload),
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            for _ in range(2):
                job = consumer._try_dequeue()
                if job is None:
                    _force_immediate_redeque(job_id)
                    job = consumer._try_dequeue()
                assert job is not None
                consumer._execute_job(job)
                _force_immediate_redeque(job_id)

        row = fetch_job(job_id)
        assert row["status"] == "DEAD", row
        assert row["attempt"] == 2
        assert row["error_class"] == "JobVerificationFailed"

        sender.assert_called_once()
        smtp_cfg, to, subject, body = sender.call_args.args
        assert to == "ops@example.com"
        assert smtp_cfg.host == "smtp.example.com"
        assert smtp_cfg.tls is False
        assert str(job_id) in subject
        assert "JobVerificationFailed" in subject
        assert "AI-102" in body
        assert "no_mcp_calls" in body
        assert "Attempt:      2/2" in body

    def test_claude_with_mcp_calls_succeeds_no_email(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch,
    ):
        sender = _patch_app_monitor(monkeypatch)
        insert_primary_token("claude")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=3, reference_id="AI-103")

        captured: list[str] = []
        payload = (FIXTURES / "good_with_mcp.jsonl").read_text()
        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.claude.src.runner.TokenClaudeRunner.run",
                _claude_callback(payload, captured=captured),
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            job = consumer._try_dequeue()
            assert job is not None
            consumer._execute_job(job)

        row = fetch_job(job_id)
        assert row["status"] == "SUCCESS", row
        assert row["session_id"] == captured[0]
        # Good fixture has one mcp__toolbox__* call → column = 1.
        assert row["toolbox_mcp_calls"] == 1
        sender.assert_not_called()

    # -- agent-agnostic proof: Codex follows the same contract --------------

    def test_codex_no_mcp_exhausts_retries_then_dead_letters_with_email(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch,
    ):
        sender = _patch_app_monitor(monkeypatch)
        insert_primary_token("codex", "o3")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=2, reference_id="AI-104")

        payload = (CODEX_FIXTURES / "codex_bad_no_mcp.jsonl").read_text()
        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.codex.src.runner.TokenCodexRunner.run",
                _codex_callback(payload),
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            for _ in range(2):
                job = consumer._try_dequeue()
                if job is None:
                    _force_immediate_redeque(job_id)
                    job = consumer._try_dequeue()
                assert job is not None
                consumer._execute_job(job)
                _force_immediate_redeque(job_id)

        row = fetch_job(job_id)
        assert row["status"] == "DEAD", row
        assert row["attempt"] == 2
        # The Codex transcript fixture only contains local tool calls
        # (``exec_command``, ``apply_patch``) — verifier vetoes via the
        # Codex-registered reader, with **no** claude-specific code in the
        # path.
        assert row["error_class"] == "JobVerificationFailed"
        assert "no_mcp_calls" in (row["error_message"] or "")

        sender.assert_called_once()
        _, _, subject, body = sender.call_args.args
        assert str(job_id) in subject
        assert "AI-104" in body
        assert "no_mcp_calls" in body

    # -- unknown provider must fail safe -----------------------------------

    def test_unknown_provider_is_trusted_no_veto_no_email(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch,
    ):
        sender = _patch_app_monitor(monkeypatch)
        # Use the claude pool/auth but report agent_type="hermes" — there is
        # no Hermes TranscriptReader registered, so the verifier must trust
        # rc=0 instead of trying to parse anything.
        insert_primary_token("claude")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=3, reference_id="AI-105")

        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.claude.src.runner.TokenClaudeRunner.run",
                _hermes_callback,
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            job = consumer._try_dequeue()
            assert job is not None
            consumer._execute_job(job)

        row = fetch_job(job_id)
        assert row["status"] == "SUCCESS", row
        sender.assert_not_called()

    # -- silent provider format drift ---------------------------------------

    def test_claude_format_drift_dead_letters_first_attempt_with_parser_alert(
        self, int_db_config, int_consumer_config, tmp_path, monkeypatch, caplog,
    ):
        sender = _patch_app_monitor(monkeypatch)
        insert_primary_token("claude")
        ws_id = _insert_workspace("acme")
        av_id = _insert_agent_view(ws_id, "developer")
        job_id = _insert_job_with_agent_view(av_id, max_attempts=3, reference_id="AI-106")

        # 10 JSON-parseable lines whose outer shape doesn't match the Claude
        # ``message.content`` envelope — simulates a silent CLI upgrade.
        drift_payload = "\n".join(
            f'{{"unexpected": "format", "v": {i}}}' for i in range(10)
        ) + "\n"

        with ExitStack() as stack:
            stack.enter_context(patch(
                "agento.modules.claude.src.runner.TokenClaudeRunner.run",
                _claude_callback(drift_payload),
            ))
            _enter_build_dir_patches(stack, tmp_path / "build")
            consumer = Consumer(int_db_config, int_consumer_config, logging.getLogger("e2e"))
            job = consumer._try_dequeue()
            assert job is not None
            with caplog.at_level(logging.ERROR, logger=obs.logger.name):
                consumer._execute_job(job)

        row = fetch_job(job_id)
        # Parser drift is non-retryable: first occurrence dead-letters and
        # immediately surfaces the issue to ops.
        assert row["status"] == "DEAD", row
        assert row["attempt"] == 1
        assert row["error_class"] == "JobVerificationFailed"
        assert "transcript_parse_failed" in (row["error_message"] or "")
        # Parser drift → measurement is unreliable, column stays NULL.
        assert row["toolbox_mcp_calls"] is None

        sender.assert_called_once()
        _, _, _, body = sender.call_args.args
        assert "transcript_parse_failed" in body
        assert "0 of 10" in body  # "parser recognized 0 of 10 JSON records ..."

        assert any(
            rec.levelno == logging.ERROR and "drift detected" in rec.getMessage()
            for rec in caplog.records
        )
