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
