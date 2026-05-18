"""Event observers for app_monitor.

- ``VerifyMcpUsageObserver`` (``job_finalize_before``) — veto an apparent
  rc=0 when the agent made zero ``mcp__toolbox__*`` tool calls. The transcript
  parser lives in the agent's module (claude/codex/…); this observer resolves
  one via ``get_transcript_reader(provider)`` so the framework — and this
  module — stay agent-agnostic.
- ``AlertEmailObserver`` (``job_dead_after``) — send a plain-text SMTP alert
  on DEAD transitions when both ``alerts/email_to`` and ``alerts/smtp_host``
  are configured.
"""
from __future__ import annotations

import logging

from agento.framework.bootstrap import get_module_config
from agento.framework.database_config import DatabaseConfig
from agento.framework.db import get_connection
from agento.framework.events import JobVerificationFailed, Verdict, VerifyReason
from agento.framework.transcript_reader import get_transcript_reader

from .constants import (
    CFG_ALERT_EMAIL_TO,
    CFG_ALERT_SMTP_FROM,
    CFG_ALERT_SMTP_HOST,
    CFG_ALERT_SMTP_PASSWORD,
    CFG_ALERT_SMTP_PORT,
    CFG_ALERT_SMTP_TLS,
    CFG_ALERT_SMTP_USER,
    CFG_MISSING_TRANSCRIPT_POLICY,
    MCP_TOOLBOX_TOOL_PREFIX,
    PARSE_DRIFT_MIN_LINES,
    POLICY_DEAD,
    POLICY_RETRY,
    POLICY_TRUST,
)
from .emailer import SmtpConfig, send_alert
from .verify_mcp_usage import verify

logger = logging.getLogger(__name__)

_MODULE_NAME = "app_monitor"


def _config() -> dict:
    return get_module_config(_MODULE_NAME) or {}


def _save_toolbox_mcp_calls(job_id: int, count: int) -> None:
    """Persist ``mcp__toolbox__*`` call count for this attempt to ``job.toolbox_mcp_calls``.

    Best-effort: a DB hiccup must not crash the verifier or change the verdict.
    NULL is reserved for "verifier could not determine the count" — only call
    this when we have a real number (transcript parsed successfully).
    """
    try:
        conn = get_connection(DatabaseConfig.from_env())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job SET toolbox_mcp_calls = %s, updated_at = NOW() "
                    "WHERE id = %s",
                    (count, job_id),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "Failed to persist toolbox_mcp_calls=%d for job_id=%s (best-effort)",
            count, job_id, exc_info=True,
        )


def _apply_missing_transcript_policy() -> Verdict | None:
    policy = _config().get(CFG_MISSING_TRANSCRIPT_POLICY, POLICY_DEAD)
    if policy == POLICY_TRUST:
        return None
    if policy == POLICY_RETRY:
        return Verdict(
            retryable=True,
            reason=VerifyReason.TRANSCRIPT_MISSING,
            fresh_start=True,
            detail="transcript JSONL not found; retrying with fresh session",
        )
    # default: POLICY_DEAD
    return Verdict(
        retryable=False,
        reason=VerifyReason.TRANSCRIPT_MISSING,
        fresh_start=False,
        detail="transcript JSONL not found; dead-lettering per policy",
    )


class VerifyMcpUsageObserver:
    """Veto rc=0 jobs that never invoked any ``mcp__toolbox__*`` tool.

    Resolves the provider-specific transcript reader via the framework
    registry — never imports a provider-specific module directly.
    """

    def execute(self, event) -> None:
        if getattr(event, "verdict", None) is not None:
            return  # earlier observer already vetoed; honor it
        job = getattr(event, "job", None)
        session_id = getattr(job, "session_id", None) if job is not None else None
        if not session_id:
            event.verdict = _apply_missing_transcript_policy()
            return

        provider = getattr(event, "provider", None)
        reader = get_transcript_reader(provider) if provider else None
        if reader is None:
            # No reader registered for this provider — we don't know how to
            # parse its transcript, so we can't verify. Trust rc=0 rather than
            # dead-letter a job whose agent module never declared a reader.
            logger.info(
                "VerifyMcpUsageObserver: no TranscriptReader for provider=%r — "
                "trusting rc=0 (job_id=%s)", provider, getattr(job, "id", "?"),
            )
            return

        try:
            summary = reader.parse(session_id)
        except FileNotFoundError:
            event.verdict = _apply_missing_transcript_policy()
            return
        except Exception:
            logger.exception(
                "VerifyMcpUsageObserver: unexpected error reading transcript "
                "for provider=%s session_id=%s — applying missing-transcript policy",
                provider, session_id,
            )
            event.verdict = _apply_missing_transcript_policy()
            return

        # Drift detection: a non-trivial transcript whose records the reader
        # didn't recognize at all is almost certainly a silent provider format
        # change. Treat it as a distinct, non-retryable verdict so the very
        # first occurrence dead-letters and (via AlertEmailObserver) pages ops
        # with a parser-specific reason — instead of silently cascading into
        # NO_MCP_CALLS vetoes that mislead diagnosis. Don't write
        # toolbox_mcp_calls when the parser failed; leave NULL to mark the
        # measurement as unreliable.
        if (
            summary.total_json_lines >= PARSE_DRIFT_MIN_LINES
            and summary.recognized_records == 0
        ):
            logger.error(
                "VerifyMcpUsageObserver: parser drift detected for provider=%s "
                "session_id=%s — %d JSON lines, 0 recognized records",
                provider, session_id, summary.total_json_lines,
            )
            event.verdict = Verdict(
                retryable=False,
                reason=VerifyReason.TRANSCRIPT_PARSE_FAILED,
                fresh_start=False,
                detail=(
                    f"parser recognized 0 of {summary.total_json_lines} "
                    f"JSON records — likely provider format change"
                ),
            )
            return

        toolbox_calls = sum(
            1 for t in summary.tool_uses if t.name.startswith(MCP_TOOLBOX_TOOL_PREFIX)
        )
        logger.info(
            "VerifyMcpUsageObserver: parsed transcript",
            extra={
                "job_id": getattr(job, "id", None),
                "provider": provider,
                "session_id": session_id,
                "toolbox_mcp_calls": toolbox_calls,
                "tool_uses_total": len(summary.tool_uses),
                "recognized_records": summary.recognized_records,
                "json_lines_total": summary.total_json_lines,
            },
        )
        job_id = getattr(job, "id", None)
        if isinstance(job_id, int) and job_id > 0:
            _save_toolbox_mcp_calls(job_id, toolbox_calls)

        event.verdict = verify(summary.tool_uses)


def _smtp_config() -> SmtpConfig | None:
    cfg = _config()
    host = (cfg.get(CFG_ALERT_SMTP_HOST) or "").strip()
    if not host:
        return None
    return SmtpConfig(
        host=host,
        port=int(cfg.get(CFG_ALERT_SMTP_PORT) or 587),
        user=(cfg.get(CFG_ALERT_SMTP_USER) or ""),
        password=(cfg.get(CFG_ALERT_SMTP_PASSWORD) or ""),
        from_addr=(cfg.get(CFG_ALERT_SMTP_FROM) or ""),
        tls=bool(cfg.get(CFG_ALERT_SMTP_TLS, True)),
    )


def _format_body(event) -> tuple[str, str]:
    """Compose a short subject/body for the DEAD alert.

    When the underlying error is a verification veto, surface
    ``verdict.reason`` and ``verdict.detail`` so ops can immediately tell a
    parser-drift dead-letter from an agent-fault dead-letter without opening
    a transcript.
    """
    job = event.job
    err = event.error
    err_class = err.__class__.__name__
    subject = f"[agento] Job {job.id} DEAD — {err_class}"
    lines = [
        f"Job id:       {job.id}",
        f"Reference id: {job.reference_id}",
        f"Source:       {job.source}",
        f"Attempt:      {job.attempt}/{job.max_attempts}",
        f"Error class:  {err_class}",
        f"Error:        {str(err)[:1000]}",
        f"Elapsed ms:   {event.elapsed_ms}",
    ]
    if isinstance(err, JobVerificationFailed):
        lines.append(f"Verdict reason: {err.verdict.reason.value}")
        if err.verdict.detail:
            lines.append(f"Verdict detail: {err.verdict.detail}")
    return subject, "\n".join(lines)


class AlertEmailObserver:
    """Send a plain-text alert on DEAD-letter transitions."""

    def execute(self, event) -> None:
        cfg = _config()
        to = (cfg.get(CFG_ALERT_EMAIL_TO) or "").strip()
        smtp = _smtp_config()
        if not to or smtp is None:
            return  # not configured — silent no-op
        subject, body = _format_body(event)
        try:
            send_alert(smtp, to, subject, body)
        except Exception:
            logger.warning(
                "AlertEmailObserver: SMTP send failed (job_id=%s)",
                getattr(event.job, "id", "?"),
                exc_info=True,
            )
