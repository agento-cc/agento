"""CLI command registry — modules contribute commands via di.json."""
from __future__ import annotations

import argparse
from typing import Protocol


class Command(Protocol):
    """Protocol for module-contributed CLI commands (Magento console command pattern)."""

    @property
    def name(self) -> str:
        """Subcommand name (e.g. 'sync', 'publish')."""
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


# Registry: name → Command instance
_COMMANDS: dict[str, Command] = {}


def register_command(command: Command) -> None:
    """Register a module-contributed command."""
    _COMMANDS[command.name] = command


def get_commands() -> dict[str, Command]:
    """Return all registered commands."""
    return dict(_COMMANDS)


def clear() -> None:
    """Reset registry (for testing)."""
    _COMMANDS.clear()
