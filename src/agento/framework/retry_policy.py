from __future__ import annotations

from dataclasses import dataclass

# Backoff delays in seconds: 1 min, 5 min, 30 min
BACKOFF_DELAYS = [60, 300, 1800]

# Exception class names that should NOT be retried
NON_RETRYABLE_ERRORS = frozenset({
    "ValueError",
    "PermissionError",
    "FileNotFoundError",
    "KeyError",
    "AuthenticationError",  # token expired — retrying won't help
})


@dataclass
class RetryDecision:
    should_retry: bool
    delay_seconds: int
    reason: str


def evaluate(error_class: str | None, attempt: int, max_attempts: int) -> RetryDecision:
    """Decide whether a failed job should be retried.

    Args:
        error_class: The __class__.__name__ of the caught exception.
        attempt: Current attempt number (1-indexed, just completed).
        max_attempts: Maximum allowed attempts.
    """
    if error_class and error_class in NON_RETRYABLE_ERRORS:
        return RetryDecision(
            should_retry=False,
            delay_seconds=0,
            reason=f"Non-retryable error: {error_class}",
        )

    if attempt >= max_attempts:
        return RetryDecision(
            should_retry=False,
            delay_seconds=0,
            reason=f"Max attempts ({max_attempts}) reached",
        )

    delay_index = min(attempt - 1, len(BACKOFF_DELAYS) - 1)
    delay = BACKOFF_DELAYS[delay_index]

    return RetryDecision(
        should_retry=True,
        delay_seconds=delay,
        reason=f"Retry {attempt + 1}/{max_attempts} after {delay}s",
    )
