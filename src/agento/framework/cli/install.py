"""agento install — interactive project installation wizard."""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import secrets
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ._output import cyan, log_error, log_info, log_warn
from ._project import find_compose_file
from ._templates import TemplateNotFoundError, extract_sql_files, get_package_version, get_template
from .terminal import select


def _sanitize_compose_name(name: str) -> str:
    """Sanitize a string for use as COMPOSE_PROJECT_NAME.

    Lowercases, replaces spaces/dots/underscores with hyphens,
    strips invalid characters, collapses consecutive hyphens.
    Falls back to 'agento' if result is empty.
    """
    name = name.lower()
    name = re.sub(r"[\s._]+", "-", name)
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name or "agento"


def _generate_password() -> str:
    """Generate a random URL-safe password."""
    return secrets.token_urlsafe(24)


def _is_port_free(port: int) -> bool:
    """Check if a TCP port is available on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _detect_timezone() -> str:
    """Detect the system timezone as an Olson name (e.g., 'Europe/Warsaw').

    Parses the /etc/localtime symlink. Falls back to 'UTC'.
    """
    try:
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        idx = parts.index("zoneinfo")
        return "/".join(parts[idx + 1:])
    except (ValueError, OSError):
        return "UTC"


def _scaffold(project_dir: Path, project_name: str, config: dict[str, str]) -> None:
    """Create project directory structure and write config files."""
    dirs = [
        ".agento",
        "app/code",
        "workspace/systems",
        "workspace/tmp",
        "logs",
        "tokens",
        "storage",
        "docker",
        "docker/sql",
    ]
    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write project.json
    project_meta = {
        "name": project_name,
        "version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
    }
    (project_dir / ".agento" / "project.json").write_text(
        json.dumps(project_meta, indent=2) + "\n"
    )

    # Write .gitignore
    try:
        gitignore = get_template("gitignore")
        (project_dir / ".gitignore").write_text(gitignore)
    except TemplateNotFoundError:
        (project_dir / ".gitignore").write_text(
            "# Agento project\n"
            "app/code/*/\n"
            "!app/code/_example/\n"
            "logs/\n"
            "tokens/\n"
            "storage/\n"
            "secrets.env\n"
            "docker/.env\n"
            "docker/.cron.env\n"
            "docker/.toolbox.env\n"
        )

    # Docker Compose config — replace version placeholder with installed package version
    try:
        compose_content = get_template("docker-compose.yml")
        compose_content = compose_content.replace("__AGENTO_VERSION__", get_package_version())
        (project_dir / "docker" / "docker-compose.yml").write_text(compose_content)
    except TemplateNotFoundError:
        pass

    # Extract SQL migration scripts from installed package
    with contextlib.suppress(Exception):
        extract_sql_files(project_dir / "docker" / "sql")

    # Render docker/.env from template
    try:
        env_template = get_template("env.example")
        env_content = env_template.format_map(config)
        (project_dir / "docker" / ".env").write_text(env_content)
    except TemplateNotFoundError:
        lines = [
            f"COMPOSE_PROJECT_NAME={config['compose_project_name']}",
            f"MYSQL_ROOT_PASSWORD={config['mysql_root_password']}",
            f"MYSQL_PASSWORD={config['mysql_password']}",
            f"MYSQL_PORT={config['mysql_port']}",
            f"TZ={config['timezone']}",
            "# Set to 1 to disable LLM API calls (mocks agent output, for testing)",
            "DISABLE_LLM=0",
            "",
        ]
        (project_dir / "docker" / ".env").write_text("\n".join(lines))

    # Write secrets.env with auto-generated encryption key
    encryption_key = secrets.token_hex(32)
    (project_dir / "secrets.env").write_text(
        "# Agento secrets — DO NOT commit this file\n"
        "\n"
        f"AGENTO_ENCRYPTION_KEY={encryption_key}\n"
    )

    # Write secrets.env.example
    try:
        secrets_content = get_template("secrets.env.example")
        (project_dir / "secrets.env.example").write_text(secrets_content)
    except TemplateNotFoundError:
        (project_dir / "secrets.env.example").write_text(
            "# Agento secrets — DO NOT commit this file\n"
            "# Copy to secrets.env and fill in your values\n"
            "\n"
            "# Jira credentials (only needed if using Jira module)\n"
            "JIRA_USER=\n"
            "JIRA_TOKEN=\n"
            "JIRA_HOST=\n"
            "\n"
            "# Encryption key for config values\n"
            "AGENTO_ENCRYPTION_KEY=\n"
        )


def _run_post_install(project_dir: Path) -> None:
    """Run agento up + setup:upgrade after scaffolding."""
    compose_file = find_compose_file(project_dir)
    if not compose_file:
        log_warn("docker-compose.yml not found. Skipping runtime startup.")
        return

    compose_cmd = ["docker", "compose", "-f", str(compose_file)]

    log_info("Starting containers...")
    result = subprocess.run([*compose_cmd, "up", "-d"])
    if result.returncode != 0:
        log_error("Failed to start containers. Run 'agento up' manually.")
        return

    # The cron entrypoint runs setup:upgrade --skip-onboarding on start and
    # touches /tmp/.setup-done when finished.  Wait for that before running
    # the interactive setup:upgrade (which only triggers onboarding — migrations
    # are already applied).
    log_info("Waiting for initial setup...")
    for _ in range(60):
        check = subprocess.run(
            [*compose_cmd, "exec", "-T", "cron", "test", "-f", "/tmp/.setup-done"],
            capture_output=True,
        )
        if check.returncode == 0:
            break
        time.sleep(2)
    else:
        log_warn("setup:upgrade timed out. Run 'agento setup:upgrade' manually.")
        return

    log_info("Running setup:upgrade...")
    result = subprocess.run(
        [*compose_cmd, "exec", "-it", "cron", "/opt/cron-agent/run.sh", "setup:upgrade"],
    )
    if result.returncode != 0:
        log_warn("setup:upgrade failed. Run 'agento setup:upgrade' manually.")


class InstallCommand:
    @property
    def name(self) -> str:
        return "install"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Install a new agento project (interactive wizard)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> None:
        # Step 1: Ask project path
        project_dir = self._ask_project_path()
        project_name = project_dir.name

        # Check if already installed
        if (project_dir / ".agento" / "project.json").is_file():
            log_info("Agento is already installed in this directory.")
            return

        # Validate directory
        if project_dir.exists():
            if any(project_dir.iterdir()):
                log_error(f"Directory is not empty: {project_dir}")
                sys.exit(1)
        else:
            project_dir.mkdir(parents=True)

        # Step 2: Ask install mode
        mode = select("Installation mode:", [
            "Basic (recommended)",
            "Advanced",
        ])

        # Collect config
        compose_name = _sanitize_compose_name(project_name)
        mysql_port = "3306"
        timezone = _detect_timezone()

        if mode == 1:  # Advanced
            compose_name = self._ask_compose_name(compose_name)
            mysql_port = self._ask_mysql_port()
            timezone = self._ask_timezone(timezone)

        config = {
            "compose_project_name": compose_name,
            "mysql_root_password": _generate_password(),
            "mysql_password": _generate_password(),
            "mysql_port": mysql_port,
            "timezone": timezone,
        }

        # Scaffold
        log_info(f"Installing agento project: {project_name}")
        _scaffold(project_dir, project_name, config)
        log_info(f"Project created at: {project_dir}")

        # Post-install: start runtime
        _run_post_install(project_dir)

        print()
        print(f"{cyan('Next steps:')}")
        print("  agento module:add <name>      Add your first module")
        print("  agento token:register claude   Register an agent token")
        print("  agento logs                    View container logs")
        print()

    def _ask_project_path(self) -> Path:
        """Prompt for project path with validation."""
        while True:
            raw = input("  Project path [.]: ").strip()
            if not raw:
                raw = "."
            project_dir = (Path.cwd() / raw).resolve()
            if project_dir.exists() and not project_dir.is_dir():
                log_error(f"Not a directory: {project_dir}")
                continue
            return project_dir

    def _ask_compose_name(self, default: str) -> str:
        """Prompt for COMPOSE_PROJECT_NAME with sanitization."""
        while True:
            raw = input(f"  Docker project name [{default}]: ").strip()
            if not raw:
                return default
            sanitized = _sanitize_compose_name(raw)
            if sanitized != raw.lower():
                log_info(f"Sanitized to: {sanitized}")
            return sanitized

    def _ask_mysql_port(self) -> str:
        """Prompt for MySQL port with validation."""
        while True:
            raw = input("  MySQL host port [3306]: ").strip()
            if not raw:
                raw = "3306"
            try:
                port = int(raw)
            except ValueError:
                log_error("Invalid port number.")
                continue
            if not (1 <= port <= 65535):
                log_error("Port must be between 1 and 65535.")
                continue
            if not _is_port_free(port):
                log_error(f"Port {port} is already in use.")
                continue
            return str(port)

    def _ask_timezone(self, default: str) -> str:
        """Prompt for timezone."""
        raw = input(f"  Timezone [{default}]: ").strip()
        return raw if raw else default
