from __future__ import annotations


class AuthenticationError(RuntimeError):
    """Raised when agent authentication fails.

    Covers two related failure modes:
    * Interactive OAuth login (``token:register`` / ``token:refresh``) — raised
      before any token record exists, so ``token_id`` is ``None``.
    * Runtime auth rejection — the agent CLI rejected a stored credential while
      executing a job (401, expired token, "Not logged in"). The consumer sets
      ``token_id`` to the id of the token it handed to the runner so the pool
      can be updated (``status='error'``) and a different token selected on retry.
    """

    def __init__(self, message: str, *, token_id: int | None = None) -> None:
        super().__init__(message)
        self.token_id = token_id
        # Set by the consumer after poisoning the offending token: True when a
        # healthy alternative remains in the pool, so the job retries onto it
        # instead of dead-lettering. ``retry_policy.evaluate`` reads this flag.
        self.retry_with_other_token = False


class UsageLimitError(RuntimeError):
    """Raised when an agent CLI rejects a run because the account hit its
    session/usage/rate limit.

    Unlike ``AuthenticationError`` this is TEMPORARY, not a poisoned credential:
    the consumer throttles the offending token until ``reset_at`` (a cooldown via
    ``oauth_token.throttled_until`` — NOT ``status='error'`` and NOT ``expires_at``)
    so the pool skips it while limited and auto-recovers afterwards, and the job
    fails over to another healthy token. ``token_id`` is set by the consumer to the
    token it handed to the runner. ``reset_at`` is a naive-UTC datetime supplied by
    the agent module's parser, or ``None`` when the CLI gave no parseable reset time
    (the consumer then applies a default throttle window).
    """

    def __init__(
        self,
        message: str,
        *,
        token_id: int | None = None,
        reset_at=None,
    ) -> None:
        super().__init__(message)
        self.token_id = token_id
        self.reset_at = reset_at
        # Set by the consumer after throttling the offending token: True when a
        # healthy alternative remains in the pool, so the job retries onto it.
        # ``retry_policy.evaluate`` reads this flag (mirrors AuthenticationError).
        self.retry_with_other_token = False
