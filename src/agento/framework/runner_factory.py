from __future__ import annotations

import logging
from collections.abc import Callable
from inspect import Parameter, signature

from .agent_manager.models import AgentProvider, Token
from .runner import Runner

# Registry: provider → factory function
_RUNNERS: dict[AgentProvider, Callable[..., Runner]] = {}


def create_runner(
    agent_type: AgentProvider,
    *,
    logger: logging.Logger | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 1200,
    model_override: str | None = None,
    working_dir: str | None = None,
    home_dir: str | None = None,
    token_override: Token | None = None,
    credentials_override: dict | None = None,
) -> Runner:
    """Create the appropriate Runner for the given AgentProvider."""
    factory = _RUNNERS.get(agent_type)
    if factory is None:
        raise ValueError(
            f"Unknown agent_type: {agent_type!r}. "
            f"Registered: {list(_RUNNERS.keys())}. Has bootstrap() been called?"
        )
    kwargs: dict = dict(
        logger=logger,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        model_override=model_override,
    )
    if working_dir is not None:
        kwargs["working_dir"] = working_dir
    if home_dir is not None:
        kwargs["home_dir"] = home_dir
    if token_override is not None and _accepts_kwarg(factory, "token_override"):
        kwargs["token_override"] = token_override
    elif token_override is not None and credentials_override is None:
        credentials_override = token_override.credentials
    if credentials_override is not None:
        kwargs["credentials_override"] = credentials_override
    return factory(**kwargs)


def _accepts_kwarg(factory: Callable[..., Runner], name: str) -> bool:
    try:
        params = signature(factory).parameters
    except (TypeError, ValueError):
        return True
    return (
        name in params
        or any(param.kind is Parameter.VAR_KEYWORD for param in params.values())
    )


def register_runner(
    agent_type: AgentProvider, factory: Callable[..., Runner]
) -> None:
    """Register a runner factory for an agent provider."""
    _RUNNERS[agent_type] = factory


def clear() -> None:
    """Reset registry (for testing)."""
    _RUNNERS.clear()
