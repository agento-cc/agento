"""agento upgrade — update Docker image version and restart containers."""
from __future__ import annotations

import argparse
import subprocess
import sys

from ._output import log_error, log_info
from ._project import find_compose_file, find_project_root, update_dotenv_value
from ._templates import get_package_version


class UpgradeCommand:
    @property
    def name(self) -> str:
        return "upgrade"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Upgrade Docker images to a new version"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--version",
            default=None,
            help="Target version (default: version of installed CLI)",
        )

    def execute(self, args: argparse.Namespace) -> None:
        project_root = find_project_root()
        if project_root is None:
            log_error("Not inside an agento project. Run 'agento install' first.")
            sys.exit(1)

        compose_file = find_compose_file(project_root)
        if compose_file is None:
            log_error("docker-compose.yml not found.")
            sys.exit(1)

        env_path = project_root / "docker" / ".env"
        if not env_path.is_file():
            log_error("docker/.env not found. Is this an agento project?")
            sys.exit(1)

        version = args.version or get_package_version()
        update_dotenv_value(env_path, "AGENTO_VERSION", version)
        log_info(f"AGENTO_VERSION set to {version}")

        compose = ["docker", "compose", "-f", str(compose_file)]

        log_info("Pulling images...")
        result = subprocess.run([*compose, "pull"])
        if result.returncode != 0:
            log_error("Failed to pull images.")
            sys.exit(result.returncode)

        log_info("Restarting containers...")
        result = subprocess.run([*compose, "up", "-d"])
        if result.returncode != 0:
            log_error("Failed to restart containers.")
            sys.exit(result.returncode)

        log_info(f"Upgraded to {version}. setup:upgrade runs automatically on container start.")
