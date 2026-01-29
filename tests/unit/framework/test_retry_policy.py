from __future__ import annotations

from agento.framework.retry_policy import BACKOFF_DELAYS, evaluate


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
