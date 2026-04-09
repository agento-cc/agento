"""agento upgrade — update CLI and Docker images to a new version."""
from __future__ import annotations

import argparse
import subprocess
import sys

from ._output import log_error, log_info, log_warn
from ._project import find_compose_file, find_project_root, update_dotenv_value
from ._templates import get_package_version


def _fetch_latest_pypi_version() -> str | None:
    """Query PyPI for the latest agento-core version."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            "https://pypi.org/pypi/agento-core/json", timeout=10,
        ) as resp:
            data = json.loads(resp.read())
            return data["info"]["version"]
    except Exception:
        return None


def _upgrade_cli(version: str | None) -> str | None:
    """Upgrade the agento-core CLI package. Returns installed version or None on failure."""
    if version:
        spec = f"agento-core=={version}"
    else:
        spec = "agento-core"

    log_info(f"Upgrading CLI ({spec})...")
    result = subprocess.run(
        ["uv", "tool", "install", "--upgrade", spec],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "is already installed" in (result.stdout + result.stderr):
            log_info("CLI already at target version.")
            return version or get_package_version()
        log_warn(f"CLI upgrade failed: {stderr}")
        return None

    # Extract installed version from uv output
    for line in (result.stdout + result.stderr).splitlines():
        if "agento-core" in line and "==" in line:
            # e.g. " + agento-core==0.3.1"  or "~ agento-core==0.3.1"
            for part in line.split():
                if part.startswith("agento-core=="):
                    return part.split("==")[1]
    return version or get_package_version()


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
            help="Target version (default: latest from PyPI)",
        )

    def execute(self, args: argparse.Namespace) -> None:
        # Resolve target version
        if args.version:
            version = args.version
        else:
            log_info("Checking latest version on PyPI...")
            version = _fetch_latest_pypi_version()
            if version is None:
                log_error("Could not fetch latest version from PyPI. Use --version to specify.")
                sys.exit(1)

        current = get_package_version()
        if version == current:
            log_info(f"CLI already at {version}.")
        else:
            installed = _upgrade_cli(version)
            if installed:
                log_info(f"CLI upgraded to {installed}.")
            else:
                log_warn("CLI upgrade failed. Continuing with Docker image upgrade.")

        # Docker image upgrade
        project_root = find_project_root()
        if project_root is None:
            log_info(f"Not inside an agento project. CLI upgraded to {version}, skipping Docker.")
            return

        compose_file = find_compose_file(project_root)
        if compose_file is None:
            log_error("docker-compose.yml not found.")
            sys.exit(1)

        env_path = project_root / "docker" / ".env"
        if not env_path.is_file():
            log_error("docker/.env not found. Is this an agento project?")
            sys.exit(1)

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
