"""agento init — scaffold a new agento project."""
from __future__ import annotations

import argparse
import importlib.resources
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ._output import cyan, log_error, log_info, log_warn


class TemplateNotFoundError(Exception):
    pass


def _get_template(name: str) -> str:
    """Read a template file from the templates directory."""
    # Try importlib.resources first (pip-installed)
    try:
        templates = importlib.resources.files("agento.framework.cli") / "templates"
        return (templates / name).read_text()
    except (TypeError, FileNotFoundError, ModuleNotFoundError):
        pass

    # Fall back to relative path (dev mode)
    template_dir = Path(__file__).parent / "templates"
    template_path = template_dir / name
    if template_path.is_file():
        return template_path.read_text()

    raise TemplateNotFoundError(name)


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold a new agento project."""
    project_name = args.project
    project_dir = Path.cwd() / project_name

    if project_dir.exists():
        log_error(f"Directory already exists: {project_dir}")
        sys.exit(1)

    local_mode = getattr(args, "local", False)

    log_info(f"Initializing agento project: {project_name}")

    # Create directory structure
    dirs = [
        ".agento",
        "app/code",
        "workspace/systems",
        "workspace/tmp",
        "logs",
        "tokens",
        "storage",
    ]
    if not local_mode:
        dirs.append("docker")

    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write project.json
    project_meta = {
        "name": project_name,
        "version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "local" if local_mode else "compose",
    }
    (project_dir / ".agento" / "project.json").write_text(
        json.dumps(project_meta, indent=2) + "\n"
    )

    # Write .gitignore
    try:
        gitignore = _get_template("gitignore")
        (project_dir / ".gitignore").write_text(gitignore)
    except TemplateNotFoundError:
        # Template not available yet — write a basic one
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

    if local_mode:
        # Local mode: generate .env with DB connection placeholders
        env_content = (
            "# Agento local dev configuration\n"
            "# Fill in your external MySQL connection details:\n"
            "CRONDB_HOST=localhost\n"
            "CRONDB_PORT=3306\n"
            "CRONDB_USER=agento\n"
            "CRONDB_PASSWORD=\n"
            "CRONDB_DATABASE=agento\n"
            "\n"
            "# Encryption key (generate with: openssl rand -hex 32)\n"
            "AGENTO_ENCRYPTION_KEY=\n"
            "\n"
            "DISABLE_LLM=0\n"
        )
        (project_dir / ".env").write_text(env_content)
        log_info("Created .env with DB connection placeholders")
    else:
        # Docker Compose mode
        try:
            compose_content = _get_template("docker-compose.yml")
            (project_dir / "docker" / "docker-compose.yml").write_text(compose_content)
        except TemplateNotFoundError:
            log_warn("docker-compose.yml template not available yet.")

        try:
            env_content = _get_template("env.example")
            (project_dir / "docker" / ".env").write_text(env_content)
        except TemplateNotFoundError:
            # Write basic .env
            (project_dir / "docker" / ".env").write_text(
                "COMPOSE_PROJECT_NAME=agento\n"
                "DISABLE_LLM=0\n"
            )

    # Write secrets.env.example
    try:
        secrets_content = _get_template("secrets.env.example")
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

    log_info(f"Project created at: {project_dir}")
    print()

    if local_mode:
        print(f"{cyan('Next steps:')}")
        print(f"  cd {project_name}")
        print("  # Edit .env with your MySQL connection details")
        print("  agento doctor                 Check prerequisites")
        print("  agento setup:upgrade          Apply migrations")
        print("  agento toolbox start          Start the toolbox locally")
    else:
        print(f"{cyan('Next steps:')}")
        print(f"  cd {project_name}")
        print("  # Edit docker/.env and secrets.env with your settings")
        print("  agento up                     Start Docker Compose")
        print("  agento setup:upgrade          Apply migrations")
        print("  agento module:add <name>      Add your first module")
    print()
