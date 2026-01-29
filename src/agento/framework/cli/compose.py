"""agento up / down / logs — Docker Compose wrappers."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from ._output import log_error, log_info, log_warn
from ._project import find_compose_file, find_project_root


def _get_compose_cmd() -> list[str]:
    """Get the base docker compose command with the project's compose file."""
    project_root = find_project_root()
    if project_root is None:
        log_error("Not inside an agento project. Run 'agento init <project>' first.")
        sys.exit(1)

    compose_file = find_compose_file(project_root)
    if compose_file is None:
        log_error("docker-compose.yml not found. Run 'agento init <project>' first.")
        sys.exit(1)

    return ["docker", "compose", "-f", str(compose_file)]


def cmd_up(args: argparse.Namespace) -> None:
    """Start the agento runtime via Docker Compose."""
    compose = _get_compose_cmd()

    log_info("Starting containers...")
    result = subprocess.run([*compose, "up", "-d"])
    if result.returncode != 0:
        log_error("Failed to start containers.")
        sys.exit(result.returncode)

    # Wait for MySQL health
    log_info("Waiting for MySQL...")
    for _ in range(30):
        check = subprocess.run(
            [*compose, "exec", "-T", "mysql", "mysqladmin", "ping", "-h", "localhost", "--silent"],
            capture_output=True,
        )
        if check.returncode == 0:
            break
        time.sleep(2)
    else:
        log_warn("MySQL may not be ready yet. Continuing anyway...")

    log_info("Containers started.")
    print()
    print("Next steps:")
    print("  agento setup:upgrade          Apply migrations and install crontab")
    print("  agento token register claude   Register an agent token")
    print("  agento logs                    View container logs")
    print()


def cmd_down(args: argparse.Namespace) -> None:
    """Stop the agento runtime."""
    compose = _get_compose_cmd()

    log_info("Stopping containers...")
    result = subprocess.run([*compose, "down"])
    if result.returncode != 0:
        log_error("Failed to stop containers.")
        sys.exit(result.returncode)

    log_info("Containers stopped.")


def cmd_logs(args: argparse.Namespace) -> None:
    """Show container logs."""
    compose = _get_compose_cmd()

    cmd = [*compose, "logs", "-f"]
    if hasattr(args, "service") and args.service:
        cmd.append(args.service)

    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        subprocess.run(cmd)
