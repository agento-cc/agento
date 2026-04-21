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
        artifacts_dir: Path,
        *,
        job_id: int,
    ) -> None: ...

    def owned_paths(self) -> tuple[set[str], set[str]]:
        """Return (files, dirs) owned by this writer.

        When copying a build into a per-job run dir, framework copies these
        items (instead of symlinking) so they can be modified per-job.
        """
        ...

    def persistent_home_paths(self) -> list[str]:
        """Return relative-to-HOME paths that must survive workspace rebuilds.

        These are session/state artifacts (e.g. ``.claude/projects``) which the
        framework symlinks from the immutable build dir to a per-agent_view
        persistent ``state/`` directory. Returning an empty list means the
        agent has no persistent home state.
        """
        ...

    def write_credentials(self, build_dir: Path, credentials: dict) -> None:
        """Materialize provider-specific OAuth credential files into ``build_dir``.

        The ``credentials`` dict is the decrypted payload from ``oauth_token.credentials``
        (flat fields: ``subscription_key``, ``refresh_token``, ``expires_at``,
        ``subscription_type``, ``id_token``, ``raw_auth``). Each provider rewrites
        it into the format its CLI expects (e.g. Claude's ``.claude/.credentials.json``
        with the ``claudeAiOauth`` nested structure, or Codex's ``.codex/auth.json``).
        Default: no-op (agent doesn't need on-disk credentials).
        """
        ...

    def migrate_legacy_workspace_config(self, build_dir: Path, workspace_root: Path) -> None:
        """Best-effort migration of legacy shared-HOME config from ``workspace_root``.

        This is used when the runtime moved from a shared ``/workspace`` HOME to
        per-agent build directories. Implementations may copy or merge their old
        config files (for example MCP settings) into the new build layout.
        Default: no-op.
        """
        ...


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


def all_owned_paths() -> tuple[set[str], set[str]]:
    """Aggregate owned (files, dirs) across every registered ConfigWriter."""
    files: set[str] = set()
    dirs: set[str] = set()
    for writer in _CONFIG_WRITERS.values():
        f, d = writer.owned_paths()
        files |= f
        dirs |= d
    return files, dirs


def all_persistent_home_paths() -> list[str]:
    """Aggregate relative-to-HOME persistent paths across every registered ConfigWriter.

    Returns a sorted, de-duplicated list. Writers that don't implement
    ``persistent_home_paths()`` (or return an empty list) contribute nothing.
    """
    paths: set[str] = set()
    for writer in _CONFIG_WRITERS.values():
        getter = getattr(writer, "persistent_home_paths", None)
        if getter is None:
            continue
        for p in getter():
            if p:
                paths.add(p)
    return sorted(paths)


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
