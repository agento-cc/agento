"""ConfigWriter protocol and registry — agent-agnostic config file generation.

Each agent module (claude, codex, etc.) implements ConfigWriter and registers
via di.json. Framework discovers writers at bootstrap and dispatches to them
by provider string.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from .agent_manager.models import AgentProvider

logger = logging.getLogger(__name__)

# Config path prefix for agent CLI settings
AGENT_CONFIG_PREFIX = "agent_view/"


@runtime_checkable
class ConfigWriter(Protocol):
    """Protocol that any agent config writer must satisfy."""

    def prepare_workspace(
        self,
        working_dir: Path,
        agent_config: dict[str, str],
        *,
        agent_view_id: int | None = None,
    ) -> None: ...

    def inject_runtime_params(
        self,
        run_dir: Path,
        *,
        job_id: int,
        workspace_code: str,
        agent_view_code: str,
    ) -> None: ...


# Registry: provider -> ConfigWriter instance
_CONFIG_WRITERS: dict[AgentProvider, ConfigWriter] = {}


def register_config_writer(provider: AgentProvider, writer: ConfigWriter) -> None:
    """Register a config writer for an agent provider."""
    _CONFIG_WRITERS[provider] = writer
    logger.debug("Registered config writer for provider %s", provider.value)


def get_config_writer(provider: AgentProvider | str) -> ConfigWriter:
    """Look up the ConfigWriter for a provider.

    Accepts either an AgentProvider enum or a provider string (e.g. "claude").
    Raises ValueError if the provider string is unknown, KeyError if no writer registered.
    """
    if isinstance(provider, str):
        provider = AgentProvider(provider)
    writer = _CONFIG_WRITERS.get(provider)
    if writer is None:
        raise KeyError(
            f"No ConfigWriter registered for provider {provider!r}. "
            f"Registered: {list(_CONFIG_WRITERS.keys())}. Has bootstrap() been called?"
        )
    return writer


def get_agent_config(resolved_config: dict[str, tuple[str, bool]]) -> dict[str, str]:
    """Extract agent_view/* paths from resolved DB overrides into a flat dict.

    Returns {relative_path: value}, e.g. {"model": "opus-4"}.
    """
    result = {}
    for path, (value, _encrypted) in resolved_config.items():
        if path.startswith(AGENT_CONFIG_PREFIX) and value is not None:
            relative = path[len(AGENT_CONFIG_PREFIX):]
            result[relative] = value
    return result


def clear() -> None:
    """Reset registry (for testing)."""
    _CONFIG_WRITERS.clear()
