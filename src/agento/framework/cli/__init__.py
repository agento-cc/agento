from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Commands that always run on the host (no Docker proxy)
_LOCAL_COMMANDS = frozenset({
    "doctor", "install", "upgrade", "up", "down", "logs",
    "module:list", "module:enable", "module:disable", "module:validate",
    "make:module",
    "run",
    # Shortcuts for local commands
    "mo:li", "mo:en", "mo:di", "mo:va", "ma:mo", "ru",
})

# Commands that need an interactive TTY (OAuth flows, onboarding prompts)
_INTERACTIVE_COMMANDS = frozenset({
    "admin", "token:register", "token:refresh", "setup:upgrade",
    # Shortcuts for interactive commands
    "to:reg", "to:ref", "se:up",
})

# Commands that MAY want a TTY (e.g. config:set in paste mode). We forward the
# TTY only when the host caller actually has one — otherwise pipe-through
# (`-T`) keeps working for CI / scripts.
_MAYBE_INTERACTIVE_COMMANDS = frozenset({
    "config:set", "config:remove",
    # Shortcuts
    "co:se", "co:re",
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
        print("Error: Not inside an agento project. Run 'agento install' first.", file=sys.stderr)
        sys.exit(1)
    compose_file = find_compose_file(project_root)
    if not compose_file:
        print("Error: docker-compose.yml not found.", file=sys.stderr)
        sys.exit(1)

    clean_argv = [a for a in argv if a != "--local"]
    cmd = _get_command(clean_argv)
    is_interactive = cmd in _INTERACTIVE_COMMANDS
    needs_tty = is_interactive or (
        cmd in _MAYBE_INTERACTIVE_COMMANDS and sys.stdin.isatty()
    )
    tty_flag = "-it" if needs_tty else "-T"
    env_flags: list[str] = []
    if needs_tty:
        term = os.environ.get("TERM", "xterm-256color")
        env_flags = ["-e", f"TERM={term}", "-e", "COLORTERM=truecolor"]

    exec_args = [
        "docker", "compose", "-f", str(compose_file),
        "exec", "-u", "agent", tty_flag, *env_flags, "cron",
        "/opt/cron-agent/run.sh", *clean_argv,
    ]

    if is_interactive:
        # Replace current process to give Docker full TTY control (mouse events, signals)
        os.execvp("docker", exec_args)
    else:
        result = subprocess.run(exec_args)
        sys.exit(result.returncode)


def _register_framework_commands() -> None:
    """Register framework commands directly (no bootstrap needed)."""
    from ..admin import AdminCommand
    from ..commands import register_command
    from .compose import DownCommand, LogsCommand, UpCommand
    from .config import (
        ConfigGetCommand,
        ConfigListCommand,
        ConfigRemoveCommand,
        ConfigResolveCommand,
        ConfigSchemaCommand,
        ConfigSetCommand,
    )
    from .doctor import DoctorCommand
    from .install import InstallCommand
    from .module import (
        MakeModuleCommand,
        ModuleDisableCommand,
        ModuleEnableCommand,
        ModuleListCommand,
        ModuleValidateCommand,
    )
    from .run import RunCommand
    from .runtime import (
        ConsumerCommand,
        E2eCommand,
        PauseCommand,
        ReplayCommand,
        ResumeCommand,
        SetupUpgradeCommand,
    )
    from .token import (
        TokenDeregisterCommand,
        TokenListCommand,
        TokenMarkErrorCommand,
        TokenRefreshCommand,
        TokenRegisterCommand,
        TokenResetCommand,
        TokenUsageCommand,
    )
    from .upgrade import UpgradeCommand

    for cmd_cls in [
        AdminCommand,
        UpCommand, DownCommand, LogsCommand,
        DoctorCommand, InstallCommand, UpgradeCommand,
        MakeModuleCommand, ModuleEnableCommand, ModuleDisableCommand, ModuleListCommand, ModuleValidateCommand,
        ConfigSetCommand, ConfigGetCommand, ConfigListCommand, ConfigRemoveCommand, ConfigSchemaCommand, ConfigResolveCommand,
        ConsumerCommand, SetupUpgradeCommand, ReplayCommand, PauseCommand, ResumeCommand, E2eCommand,
        RunCommand,
        TokenRegisterCommand, TokenRefreshCommand, TokenListCommand, TokenDeregisterCommand,
        TokenMarkErrorCommand, TokenResetCommand, TokenUsageCommand,
    ]:
        register_command(cmd_cls())


_GROUP_ORDER = [
    "project", "setup", "module", "config", "token",
    "ingress", "job", "jira", "test",
]

_GROUP_LABELS = {
    "project": "Project", "setup": "Setup", "module": "Modules",
    "config": "Configuration", "token": "Tokens", "ingress": "Ingress",
    "job": "Jobs", "jira": "Jira", "test": "Testing",
}

_STANDALONE_GROUPS = {
    "admin": "project",
    "doctor": "project", "install": "project", "up": "project",
    "down": "project", "logs": "project",
    "run": "project",
    "consumer": "job", "publish": "job", "replay": "job",
    "e2e": "test",
}

_PREFIX_GROUP_OVERRIDES = {
    "make": "module",
    "exec": "job",
}


def _command_group(name: str) -> str:
    """Determine group key for a command name."""
    if ":" in name:
        prefix = name.split(":")[0]
        return _PREFIX_GROUP_OVERRIDES.get(prefix, prefix)
    return _STANDALONE_GROUPS.get(name, "other")


def _format_help(commands: dict) -> str:
    """Format grouped help output for the CLI."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for name, cmd in commands.items():
        group = _command_group(name)
        groups.setdefault(group, []).append((name, cmd.help))

    from ._templates import get_package_version

    lines = [
        f"Agento v{get_package_version()} -- AI Agent Framework",
        "",
        "Usage: agento <command> [options]",
    ]

    ordered_keys = [k for k in _GROUP_ORDER if k in groups]
    extra_keys = sorted(k for k in groups if k not in _GROUP_ORDER)
    for group_key in ordered_keys + extra_keys:
        label = _GROUP_LABELS.get(group_key, group_key.capitalize())
        lines.append("")
        lines.append(f"{label}:")
        for name, help_text in sorted(groups[group_key]):
            lines.append(f"  {name:<20s}{help_text}")

    lines.append("")
    lines.append("Run 'agento <command> --help' for details on a specific command.")
    lines.append("")
    lines.append("Tip: Use shortcuts for faster typing (e.g. 'co:se' for 'config:set',")
    lines.append("'mo:li' for 'module:list'). Pattern: first 2 letters of each segment.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if _should_proxy(sys.argv[1:]):
        _proxy_to_docker(sys.argv[1:])

    # Strip --local escape-hatch flag before argparse sees it
    if "--local" in sys.argv:
        sys.argv = [a for a in sys.argv if a != "--local"]

    # Phase 1: Bootstrap module commands (skip for local commands that don't need modules)
    cmd = _get_command(sys.argv[1:])
    if cmd not in _LOCAL_COMMANDS:
        from ..bootstrap import bootstrap
        from ..dependency_resolver import DisabledDependencyError

        try:
            bootstrap()
        except DisabledDependencyError as e:
            print(f"Warning: {e}", file=sys.stderr)
        except Exception:
            pass  # DB unavailable etc. -- framework commands still work

    # Phase 2: Register framework commands
    _register_framework_commands()

    # Phase 3: Resolve shortcuts before argparse sees them
    from ..commands import get_commands, resolve_shortcut

    argv = sys.argv[1:]
    if argv:
        first = _get_command(argv)
        if first:
            resolved = resolve_shortcut(first)
            if resolved != first:
                idx = argv.index(first)
                argv[idx] = resolved

    # Phase 4: Build argparse from unified registry
    commands = get_commands()

    parser = argparse.ArgumentParser(prog="agento", description="Agento -- AI Agent Framework")
    parser.format_help = lambda: _format_help(commands)
    sub = parser.add_subparsers(dest="command")

    for name, cmd in commands.items():
        cmd_p = sub.add_parser(name, help=cmd.help)
        cmd.configure(cmd_p)
        cmd_p.set_defaults(func=cmd.execute)

    args = parser.parse_args(argv)

    if args.command is None:
        from ._project import find_project_root
        from .terminal import select

        if find_project_root() is None:
            from ._templates import get_package_version

            print()
            print(f"  Welcome to Agento v{get_package_version()} — AI Agent Framework")
            choice = select("Would you like to set up a new project?", [
                "Yes, set up a new project",
                "No, show help",
            ])
            if choice == 0:
                from .install import InstallCommand
                InstallCommand().execute(argparse.Namespace())
                sys.exit(0)

        print(_format_help(commands))
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
