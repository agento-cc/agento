from __future__ import annotations

from agento.framework.events import JobVerificationFailed, Verdict, VerifyReason
from agento.framework.retry_policy import BACKOFF_DELAYS, evaluate


def _veto(retryable: bool, reason: VerifyReason = VerifyReason.NO_MCP_CALLS) -> JobVerificationFailed:
    return JobVerificationFailed(Verdict(
        retryable=retryable,
        reason=reason,
        fresh_start=retryable,
    ))


def test_retryable_error_attempt_1():
    decision = evaluate("RuntimeError", attempt=1, max_attempts=3)
    assert decision.should_retry is True
    assert decision.delay_seconds == 60


def test_retryable_error_attempt_2():
    decision = evaluate("RuntimeError", attempt=2, max_attempts=3)
    assert decision.should_retry is True
    assert decision.delay_seconds == 300


def test_retryable_error_attempt_3_max_reached():
    decision = evaluate("RuntimeError", attempt=3, max_attempts=3)
    assert decision.should_retry is False


def test_non_retryable_value_error():
    decision = evaluate("ValueError", attempt=1, max_attempts=3)
    assert decision.should_retry is False
    assert "Non-retryable" in decision.reason


def test_non_retryable_permission_error():
    decision = evaluate("PermissionError", attempt=1, max_attempts=3)
    assert decision.should_retry is False


def test_non_retryable_key_error():
    decision = evaluate("KeyError", attempt=1, max_attempts=3)
    assert decision.should_retry is False


def test_unknown_error_is_retryable():
    decision = evaluate("RuntimeError", attempt=1, max_attempts=3)
    assert decision.should_retry is True


def test_none_error_class_is_retryable():
    decision = evaluate(None, attempt=1, max_attempts=3)
    assert decision.should_retry is True
    assert decision.delay_seconds == 60


def test_backoff_caps_at_last_delay():
    decision = evaluate("RuntimeError", attempt=10, max_attempts=20)
    assert decision.should_retry is True
    assert decision.delay_seconds == BACKOFF_DELAYS[-1]  # 1800


# -- JobVerificationFailed.verdict branch --------------------------------------
# These pin the contract added for the app_monitor verification gate: a
# verdict attached to the exception must drive the retry decision, overriding
# the default rules keyed on error_class.

def test_verification_veto_retryable_attempt_1():
    exc = _veto(retryable=True)
    decision = evaluate("JobVerificationFailed", attempt=1, max_attempts=3, error_obj=exc)
    assert decision.should_retry is True
    assert decision.delay_seconds == BACKOFF_DELAYS[0]
    assert "Verification veto retry" in decision.reason


def test_verification_veto_retryable_respects_max_attempts():
    exc = _veto(retryable=True)
    decision = evaluate("JobVerificationFailed", attempt=3, max_attempts=3, error_obj=exc)
    assert decision.should_retry is False
    assert "Max attempts" in decision.reason
    assert "verification veto" in decision.reason


def test_verification_veto_non_retryable_short_circuits():
    exc = _veto(retryable=False, reason=VerifyReason.TRANSCRIPT_MISSING)
    decision = evaluate("JobVerificationFailed", attempt=1, max_attempts=3, error_obj=exc)
    assert decision.should_retry is False
    assert decision.reason.startswith("Verification veto (non-retryable)")


def test_verification_veto_overrides_non_retryable_error_class():
    """A retryable verdict must override a normally-non-retryable error_class."""
    exc = _veto(retryable=True)
    decision = evaluate("ValueError", attempt=1, max_attempts=3, error_obj=exc)
    assert decision.should_retry is True
    assert decision.delay_seconds == BACKOFF_DELAYS[0]


def test_verification_veto_tightens_retryable_error_class():
    """A non-retryable verdict must override a normally-retryable error_class."""
    exc = _veto(retryable=False, reason=VerifyReason.TRANSCRIPT_PARSE_FAILED)
    decision = evaluate("RuntimeError", attempt=1, max_attempts=3, error_obj=exc)
    assert decision.should_retry is False
    assert decision.reason.startswith("Verification veto (non-retryable)")


def test_verification_veto_backoff_caps_at_last_delay():
    exc = _veto(retryable=True)
    decision = evaluate("JobVerificationFailed", attempt=10, max_attempts=20, error_obj=exc)
    assert decision.should_retry is True
    assert decision.delay_seconds == BACKOFF_DELAYS[-1]
