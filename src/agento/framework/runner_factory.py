from __future__ import annotations

import logging
from collections.abc import Callable

from .agent_manager.models import AgentProvider
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
    credentials_path: str | None = None,
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
    if credentials_path is not None:
        kwargs["credentials_path"] = credentials_path
    return factory(**kwargs)


def register_runner(
    agent_type: AgentProvider, factory: Callable[..., Runner]
) -> None:
    """Register a runner factory for an agent provider."""
    _RUNNERS[agent_type] = factory


def clear() -> None:
    """Reset registry (for testing)."""
    _RUNNERS.clear()
