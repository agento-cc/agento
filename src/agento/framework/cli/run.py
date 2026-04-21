"""`agento run <agent_view_code> [prompt]` — spawn the configured agent CLI.

Host-side LOCAL command. Two-step docker exec:
1. Query cron container for the resolved runtime (via ``agent_view:runtime``).
   When a prompt is provided, pass ``--prompt`` so the container returns the
   full headless command built by the provider's registered ``CliInvoker``.
2. Exec into sandbox with HOME + workdir set to the per-agent_view build dir,
   running the command the container told us to run.

No provider literal appears in this file — the command string comes entirely
from the CliInvoker registered by the agent module.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from ._project import find_compose_file, find_project_root


class RunCommand:
    @property
    def name(self) -> str:
        return "run"

    @property
    def shortcut(self) -> str:
        return "ru"

    @property
    def help(self) -> str:
        return (
            "Run the configured agent CLI in the sandbox container. "
            "With a prompt: headless (one-shot); without: interactive."
        )

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("agent_view_code", help="Agent view code (e.g. dev_01)")
        parser.add_argument(
            "prompt",
            nargs=argparse.REMAINDER,
            help="Optional one-shot prompt — when present, runs headless instead of interactive",
        )

    def execute(self, args: argparse.Namespace) -> None:
        project_root = find_project_root()
        if project_root is None:
            print(
                "Error: not inside an agento project. Run from the project root.",
                file=sys.stderr,
            )
            sys.exit(1)

        compose_file = find_compose_file(project_root)
        if compose_file is None:
            print("Error: docker-compose.yml not found.", file=sys.stderr)
            sys.exit(1)

        prompt = " ".join(args.prompt).strip()
        runtime = _fetch_runtime(compose_file, args.agent_view_code, prompt=prompt)
        provider = runtime.get("provider")
        if provider is None:
            print(
                f"Error: agent_view '{args.agent_view_code}' has no provider configured.\n"
                f"  Set it with:\n"
                f"    agento config:set agent_view/provider <provider> "
                f"--agent-view {args.agent_view_code}",
                file=sys.stderr,
            )
            sys.exit(1)

        command = runtime.get("headless_command") if prompt else runtime.get("interactive_command")
        if not command:
            print(
                f"Error: provider {provider!r} has no CliInvoker registered. "
                f"The agent module must declare one under 'cli_invokers' in di.json.",
                file=sys.stderr,
            )
            sys.exit(1)

        home_in_container = runtime["home"]
        if not _host_build_exists(project_root, runtime):
            print(
                f"Error: no build found for agent_view '{args.agent_view_code}'.\n"
                f"  Build it with:\n"
                f"    agento workspace:build --agent-view {args.agent_view_code}",
                file=sys.stderr,
            )
            sys.exit(1)

        if prompt:
            exec_args = [
                "docker", "compose", "-f", str(compose_file),
                "exec", "-T",
                "-e", f"HOME={home_in_container}",
                "-w", home_in_container,
                "sandbox",
                *command,
            ]
            result = subprocess.run(exec_args, stdin=subprocess.DEVNULL)
            sys.exit(result.returncode)

        term = os.environ.get("TERM", "xterm-256color")
        exec_args = [
            "docker", "compose", "-f", str(compose_file),
            "exec", "-it",
            "-e", f"HOME={home_in_container}",
            "-e", f"TERM={term}",
            "-e", "COLORTERM=truecolor",
            "-w", home_in_container,
            "sandbox",
            *command,
        ]
        os.execvp("docker", exec_args)


def _fetch_runtime(
    compose_file: Path, agent_view_code: str, *, prompt: str = "",
) -> dict:
    """Ask the cron container for the runtime profile; return parsed JSON."""
    cmd = [
        "docker", "compose", "-f", str(compose_file),
        "exec", "-T", "cron",
        "/opt/cron-agent/run.sh", "agent_view:runtime", agent_view_code,
    ]
    if prompt:
        cmd.extend(["--prompt", prompt])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        print(
            f"Error: could not parse runtime JSON from cron: {exc}\n"
            f"  stdout was: {result.stdout!r}",
            file=sys.stderr,
        )
        sys.exit(1)


def _host_build_exists(project_root: Path, runtime: dict) -> bool:
    """Check that workspace/build/<ws>/<av>/current exists on the host."""
    ws = runtime.get("workspace_code")
    av = runtime.get("agent_view_code")
    if not ws or not av:
        return False
    current = project_root / "workspace" / "build" / ws / av / "current"
    return current.is_symlink() or current.exists()
