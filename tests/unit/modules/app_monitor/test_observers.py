from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from agento.framework.events import JobVerificationFailed, Verdict, VerifyReason
from agento.framework.transcript_reader import ParseSummary, ToolUse
from agento.modules.app_monitor.src import observers as obs
from agento.modules.app_monitor.src.constants import (
    CFG_ALERT_EMAIL_TO,
    CFG_ALERT_SMTP_FROM,
    CFG_ALERT_SMTP_HOST,
    CFG_ALERT_SMTP_PASSWORD,
    CFG_ALERT_SMTP_PORT,
    CFG_ALERT_SMTP_TLS,
    CFG_ALERT_SMTP_USER,
    CFG_MISSING_TRANSCRIPT_POLICY,
    POLICY_RETRY,
    POLICY_TRUST,
)


@dataclass
class _Job:
    id: int = 7
    reference_id: str = "AI-70"
    source: str = "jira"
    attempt: int = 1
    max_attempts: int = 3
    session_id: str | None = None


@dataclass
class _FinalizeEvent:
    job: _Job
    verdict: object | None = None
    elapsed_ms: int = 0
    job_result: object | None = None
    provider: str | None = "claude"


@dataclass
class _DeadEvent:
    job: _Job
    error: Exception
    elapsed_ms: int = 0


class _FakeReader:
    """In-memory TranscriptReader stub keyed by session_id."""

    def __init__(self, summaries: dict[str, ParseSummary] | None = None):
        self.summaries = summaries or {}

    def parse(self, session_id: str) -> ParseSummary:
        if session_id not in self.summaries:
            raise FileNotFoundError(session_id)
        return self.summaries[session_id]

    def iter_tool_uses(self, session_id: str) -> tuple[ToolUse, ...]:
        return self.parse(session_id).tool_uses


def _summary(tool_use_names: list[str], *, total_json_lines: int | None = None,
             recognized_records: int | None = None) -> ParseSummary:
    tool_uses = tuple(ToolUse(name=n, tool_use_id=f"t{i}") for i, n in enumerate(tool_use_names))
    # Default: every tool use is "recognized" and we tack on a couple of
    # non-tool-use lines so total_json_lines > recognized_records is realistic.
    if recognized_records is None:
        recognized_records = max(len(tool_uses), 1)
    if total_json_lines is None:
        total_json_lines = recognized_records + 2
    return ParseSummary(
        total_json_lines=total_json_lines,
        recognized_records=recognized_records,
        tool_uses=tool_uses,
    )


@pytest.fixture
def fake_reader(monkeypatch):
    reader = _FakeReader({
        "good_with_mcp": _summary(["Read", "mcp__toolbox__jira_get_issue"]),
        "bad_no_mcp": _summary(["Read", "Bash"]),
    })
    monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: reader)
    return reader


def _patch_config(monkeypatch, **kwargs):
    monkeypatch.setattr(obs, "_config", lambda: kwargs)


class TestVerifyMcpUsageObserver:
    def test_skips_when_verdict_already_set(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        existing = object()
        event = _FinalizeEvent(job=_Job(session_id="good_with_mcp"), verdict=existing)
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is existing

    def test_passes_with_mcp_toolbox_call(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        event = _FinalizeEvent(job=_Job(session_id="good_with_mcp"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is None

    def test_vetoes_when_no_mcp_calls(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        event = _FinalizeEvent(job=_Job(session_id="bad_no_mcp"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.NO_MCP_CALLS
        assert event.verdict.fresh_start is True

    def test_missing_transcript_policy_dead_by_default(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)  # no key set → default DEAD
        event = _FinalizeEvent(job=_Job(session_id="nope"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.TRANSCRIPT_MISSING
        assert event.verdict.retryable is False

    def test_missing_transcript_policy_retry(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch, **{CFG_MISSING_TRANSCRIPT_POLICY: POLICY_RETRY})
        event = _FinalizeEvent(job=_Job(session_id="nope"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is not None
        assert event.verdict.retryable is True
        assert event.verdict.fresh_start is True

    def test_missing_transcript_policy_trust(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch, **{CFG_MISSING_TRANSCRIPT_POLICY: POLICY_TRUST})
        event = _FinalizeEvent(job=_Job(session_id="nope"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is None  # trust rc=0

    def test_no_session_id_applies_policy(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch, **{CFG_MISSING_TRANSCRIPT_POLICY: POLICY_RETRY})
        event = _FinalizeEvent(job=_Job(session_id=None))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.TRANSCRIPT_MISSING

    def test_no_reader_registered_trusts_run(self, monkeypatch):
        """Provider with no registered TranscriptReader → we can't verify; trust rc=0."""
        _patch_config(monkeypatch)  # default DEAD if we WERE verifying
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: None)
        event = _FinalizeEvent(
            job=_Job(session_id="any"),
            provider="unknown-provider",
        )
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is None  # no veto without a reader

    def test_no_provider_trusts_run(self, monkeypatch):
        _patch_config(monkeypatch)
        monkeypatch.setattr(
            obs, "get_transcript_reader",
            lambda provider: pytest.fail("should not be called when provider is None"),
        )
        event = _FinalizeEvent(job=_Job(session_id="any"), provider=None)
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is None

    def test_reader_raising_unexpected_error_applies_policy(self, monkeypatch):
        _patch_config(monkeypatch, **{CFG_MISSING_TRANSCRIPT_POLICY: POLICY_RETRY})

        class _Broken:
            def parse(self, session_id):
                raise RuntimeError("disk corrupted")

            def iter_tool_uses(self, session_id):
                return self.parse(session_id)

        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: _Broken())
        event = _FinalizeEvent(job=_Job(session_id="any"))
        obs.VerifyMcpUsageObserver().execute(event)
        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.TRANSCRIPT_MISSING


class TestVerifyMcpUsageObserverToolboxCount:
    """``toolbox_mcp_calls`` column population. We assert the call shape only;
    the integration test pins the actual SQL effect on a real DB row.
    """

    def test_persists_zero_when_no_mcp_calls(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        saver = MagicMock()
        monkeypatch.setattr(obs, "_save_toolbox_mcp_calls", saver)
        event = _FinalizeEvent(job=_Job(id=42, session_id="bad_no_mcp"))
        obs.VerifyMcpUsageObserver().execute(event)
        saver.assert_called_once_with(42, 0)

    def test_persists_count_when_mcp_calls_present(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        saver = MagicMock()
        monkeypatch.setattr(obs, "_save_toolbox_mcp_calls", saver)
        event = _FinalizeEvent(job=_Job(id=43, session_id="good_with_mcp"))
        obs.VerifyMcpUsageObserver().execute(event)
        # good_with_mcp fixture has exactly one mcp__toolbox__* tool use.
        saver.assert_called_once_with(43, 1)

    def test_skips_persist_when_parser_drift(self, monkeypatch):
        """Drift verdict → leave column NULL (count is unreliable)."""
        _patch_config(monkeypatch)
        reader = _FakeReader({
            "drifted": ParseSummary(
                total_json_lines=10, recognized_records=0, tool_uses=(),
            ),
        })
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: reader)
        saver = MagicMock()
        monkeypatch.setattr(obs, "_save_toolbox_mcp_calls", saver)
        event = _FinalizeEvent(job=_Job(id=44, session_id="drifted"))
        obs.VerifyMcpUsageObserver().execute(event)
        saver.assert_not_called()

    def test_skips_persist_when_transcript_missing(self, fake_reader, monkeypatch):
        _patch_config(monkeypatch)
        saver = MagicMock()
        monkeypatch.setattr(obs, "_save_toolbox_mcp_calls", saver)
        event = _FinalizeEvent(job=_Job(id=45, session_id="nope"))
        obs.VerifyMcpUsageObserver().execute(event)
        saver.assert_not_called()

    def test_skips_persist_when_no_reader_for_provider(self, monkeypatch):
        _patch_config(monkeypatch)
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: None)
        saver = MagicMock()
        monkeypatch.setattr(obs, "_save_toolbox_mcp_calls", saver)
        event = _FinalizeEvent(
            job=_Job(id=46, session_id="any"),
            provider="unknown",
        )
        obs.VerifyMcpUsageObserver().execute(event)
        saver.assert_not_called()


class TestVerifyMcpUsageObserverDrift:
    """Coverage for Fix 3 — silent parser-drift detection."""

    def test_drift_detected_emits_parse_failed_verdict(self, monkeypatch, caplog):
        _patch_config(monkeypatch)
        reader = _FakeReader({
            "drifted": ParseSummary(
                total_json_lines=10, recognized_records=0, tool_uses=(),
            ),
        })
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: reader)

        event = _FinalizeEvent(job=_Job(session_id="drifted"))
        with caplog.at_level(logging.ERROR, logger=obs.logger.name):
            obs.VerifyMcpUsageObserver().execute(event)

        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.TRANSCRIPT_PARSE_FAILED
        assert event.verdict.retryable is False
        assert event.verdict.fresh_start is False
        assert event.verdict.detail is not None
        assert "0 of 10" in event.verdict.detail
        assert any(rec.levelno == logging.ERROR for rec in caplog.records)

    def test_short_unrecognized_file_falls_through_to_no_mcp_veto(self, monkeypatch):
        """Below PARSE_DRIFT_MIN_LINES, we don't treat unrecognized records as
        drift — too noisy. The normal NO_MCP_CALLS veto still fires."""
        _patch_config(monkeypatch)
        reader = _FakeReader({
            "short": ParseSummary(
                total_json_lines=2, recognized_records=0, tool_uses=(),
            ),
        })
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: reader)

        event = _FinalizeEvent(job=_Job(session_id="short"))
        obs.VerifyMcpUsageObserver().execute(event)

        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.NO_MCP_CALLS

    def test_recognized_records_with_no_mcp_uses_existing_veto(self, monkeypatch):
        """Records were recognized but no MCP — existing NO_MCP_CALLS path, not drift."""
        _patch_config(monkeypatch)
        reader = _FakeReader({
            "no_mcp_but_parsed": ParseSummary(
                total_json_lines=10,
                recognized_records=8,
                tool_uses=(ToolUse(name="Read", tool_use_id="t1"),),
            ),
        })
        monkeypatch.setattr(obs, "get_transcript_reader", lambda provider: reader)

        event = _FinalizeEvent(job=_Job(session_id="no_mcp_but_parsed"))
        obs.VerifyMcpUsageObserver().execute(event)

        assert event.verdict is not None
        assert event.verdict.reason == VerifyReason.NO_MCP_CALLS


class TestAlertEmailObserver:
    def test_noop_when_no_email_to(self, monkeypatch):
        _patch_config(monkeypatch, **{
            CFG_ALERT_EMAIL_TO: "",
            CFG_ALERT_SMTP_HOST: "smtp.example.com",
        })
        sender = MagicMock()
        monkeypatch.setattr(obs, "send_alert", sender)
        obs.AlertEmailObserver().execute(_DeadEvent(job=_Job(), error=RuntimeError("x")))
        sender.assert_not_called()

    def test_noop_when_no_smtp_host(self, monkeypatch):
        _patch_config(monkeypatch, **{
            CFG_ALERT_EMAIL_TO: "ops@example.com",
            CFG_ALERT_SMTP_HOST: "",
        })
        sender = MagicMock()
        monkeypatch.setattr(obs, "send_alert", sender)
        obs.AlertEmailObserver().execute(_DeadEvent(job=_Job(), error=RuntimeError("x")))
        sender.assert_not_called()

    def test_sends_when_configured(self, monkeypatch):
        _patch_config(monkeypatch, **{
            CFG_ALERT_EMAIL_TO: "ops@example.com",
            CFG_ALERT_SMTP_HOST: "smtp.example.com",
            CFG_ALERT_SMTP_PORT: 587,
            CFG_ALERT_SMTP_USER: "u",
            CFG_ALERT_SMTP_PASSWORD: "p",
            CFG_ALERT_SMTP_FROM: "agento@example.com",
            CFG_ALERT_SMTP_TLS: True,
        })
        sender = MagicMock()
        monkeypatch.setattr(obs, "send_alert", sender)

        event = _DeadEvent(job=_Job(id=42, reference_id="AI-70"),
                           error=RuntimeError("boom"), elapsed_ms=500)
        obs.AlertEmailObserver().execute(event)

        sender.assert_called_once()
        smtp_cfg, to, subject, body = sender.call_args.args
        assert to == "ops@example.com"
        assert smtp_cfg.host == "smtp.example.com"
        assert smtp_cfg.tls is True
        assert "42" in subject
        assert "RuntimeError" in subject
        assert "AI-70" in body
        assert "boom" in body

    def test_body_includes_verdict_reason_and_detail_on_verification_failure(self, monkeypatch):
        """Alert email must surface verdict reason + detail when DEAD was
        triggered by a verification veto — ops needs the parser/agent
        distinction without opening a transcript."""
        _patch_config(monkeypatch, **{
            CFG_ALERT_EMAIL_TO: "ops@example.com",
            CFG_ALERT_SMTP_HOST: "smtp.example.com",
            CFG_ALERT_SMTP_PORT: 587,
            CFG_ALERT_SMTP_FROM: "agento@example.com",
            CFG_ALERT_SMTP_TLS: False,
        })
        sender = MagicMock()
        monkeypatch.setattr(obs, "send_alert", sender)

        verdict = Verdict(
            retryable=False,
            reason=VerifyReason.TRANSCRIPT_PARSE_FAILED,
            fresh_start=False,
            detail="parser recognized 0 of 18 JSON records — likely provider format change",
        )
        event = _DeadEvent(
            job=_Job(id=99, reference_id="AI-70"),
            error=JobVerificationFailed(verdict),
        )
        obs.AlertEmailObserver().execute(event)

        sender.assert_called_once()
        _, _, _, body = sender.call_args.args
        assert "transcript_parse_failed" in body
        assert "parser recognized 0 of 18" in body

    def test_smtp_failure_is_swallowed(self, monkeypatch):
        _patch_config(monkeypatch, **{
            CFG_ALERT_EMAIL_TO: "ops@example.com",
            CFG_ALERT_SMTP_HOST: "smtp.example.com",
            CFG_ALERT_SMTP_PORT: 587,
            CFG_ALERT_SMTP_FROM: "agento@example.com",
            CFG_ALERT_SMTP_TLS: False,
        })
        def _boom(*_a, **_kw):
            raise OSError("network down")
        monkeypatch.setattr(obs, "send_alert", _boom)
        obs.AlertEmailObserver().execute(
            _DeadEvent(job=_Job(), error=RuntimeError("x")),
        )
