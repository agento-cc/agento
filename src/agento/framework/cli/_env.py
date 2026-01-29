"""Simple .env file parser — no external dependencies."""
from __future__ import annotations

import os
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Skips comments and empty lines."""
    result = {}
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def load_project_env(project_root: Path) -> dict[str, str]:
    """Load env vars from project .env files (lowest to highest priority).

    Priority (lowest first):
    1. docker/.env
    2. docker/.toolbox.env / docker/.cron.env
    3. secrets.env (project root or parent)
    4. Current shell environment (highest)
    """
    env = {}

    # Load files in priority order (lowest first, higher overrides)
    for relative in [
        "docker/.env",
        "docker/.toolbox.env",
        "docker/.cron.env",
    ]:
        env.update(parse_env_file(project_root / relative))

    # secrets.env — check project root and parent
    for candidate in [project_root / "secrets.env", project_root.parent / "secrets.env"]:
        if candidate.is_file():
            env.update(parse_env_file(candidate))
            break

    # Shell environment overrides everything
    env.update(os.environ)
    return env
