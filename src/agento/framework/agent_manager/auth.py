"""Interactive OAuth authentication for agent CLI tools.

Launches ``claude`` or ``codex`` CLI in an isolated temporary HOME directory
to perform OAuth, then extracts and normalises credentials to the internal
JSON format used by token runners.

The isolation prevents the auth flow from overwriting the main active
credentials at ``/workspace/.claude`` or ``/workspace/.codex``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import AgentProvider


class AuthenticationError(RuntimeError):
    """Raised when the interactive auth flow fails or is cancelled."""


@dataclass
class AuthResult:
    """Normalised credentials extracted after successful OAuth."""

    subscription_key: str
    refresh_token: str | None
    expires_at: int | None
    subscription_type: str | None
    id_token: str | None = None
    raw_auth: dict | None = None  # Native auth.json for agents that need it (Codex)


@runtime_checkable
class AuthStrategy(Protocol):
    """Protocol for provider-specific authentication flows."""

    def authenticate(self, tmp_home: str, logger: logging.Logger) -> AuthResult: ...


# ---------------------------------------------------------------------------
# Auth strategy registry
# ---------------------------------------------------------------------------

_STRATEGIES: dict[AgentProvider, AuthStrategy] = {}


def register_auth_strategy(provider: AgentProvider, strategy: AuthStrategy) -> None:
    _STRATEGIES[provider] = strategy


def get_auth_strategy(provider: AgentProvider) -> AuthStrategy | None:
    return _STRATEGIES.get(provider)


def clear_auth_strategies() -> None:
    _STRATEGIES.clear()


def get_available_providers() -> list[AgentProvider]:
    """Return providers that have a registered auth strategy."""
    return list(_STRATEGIES.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def authenticate_interactive(
    agent_type: AgentProvider,
    logger: logging.Logger | None = None,
) -> AuthResult:
    """Run interactive OAuth for the given agent type.

    Creates an isolated temp HOME directory so the auth flow does NOT
    touch ``~/.claude`` or ``~/.codex`` (symlinked to ``/workspace/``).

    Raises :class:`AuthenticationError` on failure or user cancellation.
    """
    _log = logger or logging.getLogger(__name__)

    strategy = _STRATEGIES.get(agent_type)
    if strategy is None:
        raise ValueError(f"No auth strategy registered for: {agent_type.value}")

    tmp_home = tempfile.mkdtemp(prefix=f"auth_{agent_type.value}_")
    _log.info(f"Using isolated HOME: {tmp_home}")

    try:
        return strategy.authenticate(tmp_home, _log)
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)
        _log.debug(f"Cleaned up temp HOME: {tmp_home}")


def save_credentials(auth_result: AuthResult, output_path: str) -> None:
    """Save normalised credentials to a JSON file.

    Creates parent directories if needed.
    """
    data = {
        "subscription_key": auth_result.subscription_key,
        "refresh_token": auth_result.refresh_token,
        "expires_at": auth_result.expires_at,
        "subscription_type": auth_result.subscription_type,
        "id_token": auth_result.id_token,
        "raw_auth": auth_result.raw_auth,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Shared CLI helper (used by strategy implementations in modules)
# ---------------------------------------------------------------------------

def _run_cli(cmd: list[str], tmp_home: str, name: str) -> None:
    """Run a CLI command with isolated HOME. Raises on failure."""
    env = {**os.environ, "HOME": tmp_home}
    try:
        proc = subprocess.run(cmd, env=env)
    except FileNotFoundError as exc:
        raise AuthenticationError(f"{name} CLI not found. Is it installed?") from exc

    if proc.returncode != 0:
        raise AuthenticationError(
            f"{name} login failed with exit code {proc.returncode}"
        )
