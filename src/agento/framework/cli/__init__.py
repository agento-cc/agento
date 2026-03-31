from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Commands that always run on the host (no Docker proxy)
_LOCAL_COMMANDS = frozenset({
    "doctor", "init", "up", "down", "logs",
    "module:list", "module:enable", "module:disable", "module:validate",
    "make:module",
    # Shortcuts for local commands
    "mo:li", "mo:en", "mo:di", "mo:va", "ma:mo",
})

# Commands that need an interactive TTY (OAuth flows, onboarding prompts)
_INTERACTIVE_COMMANDS = frozenset({
    "token:register", "token:refresh", "setup:upgrade",
    # Shortcuts for interactive commands
    "to:reg", "to:ref", "se:up",
})


def _get_command(argv: list[str]) -> str | None:
    """Extract command name from argv (first non-flag arg)."""
    parts = [a for a in argv if not a.startswith("-")]
    if not parts:
        return None
    return parts[0]


def _should_proxy(argv: list[str]) -> bool:
    """Check if this command should be proxied to the Docker cron container."""
    if Path("/.dockerenv").exists():
        return False  # Already in Docker
    if "--local" in argv:
        return False  # Escape hatch
    cmd = _get_command(argv)
    return cmd is not None and cmd not in _LOCAL_COMMANDS


def _proxy_to_docker(argv: list[str]) -> None:
    """Exec command inside the cron container via docker compose."""
    from ._project import find_compose_file, find_project_root

    project_root = find_project_root()
    if not project_root:
        print("Error: Not inside an agento project. Run 'agento init' first.", file=sys.stderr)
        sys.exit(1)
    compose_file = find_compose_file(project_root)
    if not compose_file:
        print("Error: docker-compose.yml not found.", file=sys.stderr)
        sys.exit(1)

    clean_argv = [a for a in argv if a != "--local"]
    cmd = _get_command(clean_argv)
    tty_flag = "-it" if cmd in _INTERACTIVE_COMMANDS else "-T"
    result = subprocess.run([
        "docker", "compose", "-f", str(compose_file),
        "exec", tty_flag, "cron",
        "/opt/cron-agent/run.sh", *clean_argv,
    ])
    sys.exit(result.returncode)


def _register_framework_commands() -> None:
    """Register framework commands directly (no bootstrap needed)."""
    from ..commands import register_command
    from .compose import DownCommand, LogsCommand, UpCommand
    from .config import ConfigGetCommand, ConfigListCommand, ConfigRemoveCommand, ConfigSetCommand
    from .doctor import DoctorCommand
    from .init import InitCommand
    from .module import (
        MakeModuleCommand,
        ModuleDisableCommand,
        ModuleEnableCommand,
        ModuleListCommand,
        ModuleValidateCommand,
    )
    from .runtime import ConsumerCommand, E2eCommand, ReplayCommand, RotateCommand, SetupUpgradeCommand
    from .token import (
        TokenDeregisterCommand,
        TokenListCommand,
        TokenRefreshCommand,
        TokenRegisterCommand,
        TokenSetCommand,
        TokenUsageCommand,
    )

    for cmd_cls in [
        UpCommand, DownCommand, LogsCommand,
        DoctorCommand, InitCommand,
        MakeModuleCommand, ModuleEnableCommand, ModuleDisableCommand, ModuleListCommand, ModuleValidateCommand,
        ConfigSetCommand, ConfigGetCommand, ConfigListCommand, ConfigRemoveCommand,
        ConsumerCommand, SetupUpgradeCommand, ReplayCommand, RotateCommand, E2eCommand,
        TokenRegisterCommand, TokenRefreshCommand, TokenListCommand, TokenDeregisterCommand, TokenSetCommand, TokenUsageCommand,
    ]:
        register_command(cmd_cls())


def main() -> None:
    if _should_proxy(sys.argv[1:]):
        _proxy_to_docker(sys.argv[1:])

    # Phase 1: Bootstrap module commands (may fail without DB)
    from ..bootstrap import bootstrap
    from ..dependency_resolver import DisabledDependencyError

    try:
        bootstrap()
    except DisabledDependencyError as e:
        print(f"Warning: {e}", file=sys.stderr)
    except Exception:
        pass  # DB unavailable etc. -- framework commands still work

    # Phase 2: Register framework commands (after bootstrap, which clears registries)
    _register_framework_commands()

    # Phase 3: Build argparse from unified registry
    from ..commands import get_commands, get_shortcuts

    parser = argparse.ArgumentParser(prog="agento", description="Agento -- AI Agent Framework")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, cmd in get_commands().items():
        cmd_p = sub.add_parser(name, help=cmd.help)
        cmd.configure(cmd_p)
        cmd_p.set_defaults(func=cmd.execute)

    # Register shortcut aliases
    registered_names = set(get_commands().keys())
    for sc, cmd_name in get_shortcuts().items():
        if sc not in registered_names:
            cmd = get_commands()[cmd_name]
            alias_p = sub.add_parser(sc, help=f"Shortcut for {cmd_name}")
            cmd.configure(alias_p)
            alias_p.set_defaults(func=cmd.execute)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
