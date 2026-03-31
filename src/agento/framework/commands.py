"""CLI command registry — modules contribute commands via di.json."""
from __future__ import annotations

import argparse
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Command(Protocol):
    """Protocol for module-contributed CLI commands (Magento console command pattern)."""

    @property
    def name(self) -> str:
        """Subcommand name (e.g. 'sync', 'publish')."""
        ...

    @property
    def shortcut(self) -> str:
        """Short alias (e.g. 'se:up' for 'setup:upgrade'). Empty string = no shortcut."""
        ...

    @property
    def help(self) -> str:
        """Help text for argparse."""
        ...

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """Add arguments to the subparser."""
        ...

    def execute(self, args: argparse.Namespace) -> None:
        """Execute the command."""
        ...


# Registry: name -> Command instance
_COMMANDS: dict[str, Command] = {}

# Shortcut registry: shortcut -> command name
_SHORTCUTS: dict[str, str] = {}


def register_command(command: Command) -> None:
    """Register a command with optional shortcut."""
    _COMMANDS[command.name] = command
    sc = command.shortcut
    if sc:
        if sc in _SHORTCUTS:
            logger.warning(
                "Shortcut %r already registered for %r, ignoring duplicate from %r",
                sc, _SHORTCUTS[sc], command.name,
            )
        else:
            _SHORTCUTS[sc] = command.name


def get_commands() -> dict[str, Command]:
    """Return all registered commands."""
    return dict(_COMMANDS)


def get_shortcuts() -> dict[str, str]:
    """Return all registered shortcuts (shortcut -> command name)."""
    return dict(_SHORTCUTS)


def clear() -> None:
    """Reset registry (for testing)."""
    _COMMANDS.clear()
    _SHORTCUTS.clear()
