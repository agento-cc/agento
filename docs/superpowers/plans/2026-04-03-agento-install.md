# agento install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `agento init` with an interactive `agento install` wizard that supports basic/advanced modes, multi-instance Docker setups, auto-generated credentials, and automatic runtime startup.

**Architecture:** New `InstallCommand` in `cli/install.py` orchestrates an interactive wizard. Template utilities extracted to `cli/_templates.py`. Docker Compose template updated to remove hardcoded container names and parameterize the MySQL port. The CLI main entrypoint auto-redirects bare `agento` to the install wizard when outside a project.

**Tech Stack:** Python stdlib (`secrets`, `socket`, `re`, `pathlib`), existing `terminal.select()` for arrow-key prompts, `str.format_map()` for template rendering.

**Spec:** `docs/superpowers/specs/2026-04-03-agento-install-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/agento/framework/cli/_templates.py` | Create | Shared template loading (`get_template()`, `TemplateNotFoundError`) |
| `src/agento/framework/cli/install.py` | Create | Install wizard: prompts, validation, scaffolding, post-install |
| `src/agento/framework/cli/init.py` | Delete | Replaced by install.py |
| `src/agento/framework/cli/__init__.py` | Modify | Register InstallCommand, remove InitCommand, auto-detect in main() |
| `src/agento/framework/cli/compose.py` | Modify | Update error messages: "agento init" → "agento install" |
| `src/agento/framework/cli/_project.py` | Modify | Update docstring comment |
| `src/agento/framework/cli/templates/env.example` | Modify | Convert to renderable template with placeholders |
| `src/agento/framework/cli/templates/docker-compose.yml` | Modify | Remove container_name, parameterize MySQL port |
| `CLAUDE.md` | Modify | Add DX convention: arrow-key select for all prompts |
| `docs/getting-started.md` | Modify | Reference `agento install` |
| `tests/unit/framework/cli/test_templates.py` | Create | Tests for template loading |
| `tests/unit/framework/cli/test_install.py` | Create | Tests for install wizard |
| `tests/unit/framework/cli/test_init.py` | Delete | Replaced by test_install.py |

---

## Task 1: Extract template utilities to `_templates.py`

**Files:**
- Create: `src/agento/framework/cli/_templates.py`
- Test: `tests/unit/framework/cli/test_templates.py`

- [ ] **Step 1: Write tests for template loading**

```python
# tests/unit/framework/cli/test_templates.py
"""Tests for template loading utilities."""
from __future__ import annotations

import pytest
from unittest.mock import patch
from pathlib import Path

from agento.framework.cli._templates import get_template, TemplateNotFoundError


class TestGetTemplate:
    def test_reads_existing_template(self):
        result = get_template("gitignore")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_raises_on_missing_template(self):
        with (
            patch("agento.framework.cli._templates.importlib.resources.files", side_effect=ModuleNotFoundError),
            patch("agento.framework.cli._templates.Path") as mock_path,
        ):
            mock_path.return_value.parent.__truediv__ = lambda self, x: Path("/nonexistent")
            with pytest.raises(TemplateNotFoundError):
                get_template("nonexistent_template_xyz")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/framework/cli/test_templates.py -v`
Expected: FAIL — `_templates` module does not exist yet.

- [ ] **Step 3: Create `_templates.py`**

```python
# src/agento/framework/cli/_templates.py
"""Shared template loading utilities."""
from __future__ import annotations

import importlib.resources
from pathlib import Path


class TemplateNotFoundError(Exception):
    pass


def get_template(name: str) -> str:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/framework/cli/test_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agento/framework/cli/_templates.py tests/unit/framework/cli/test_templates.py
git commit -m "refactor: extract template utilities to _templates.py"
```

---

## Task 2: Update Docker Compose template

**Files:**
- Modify: `src/agento/framework/cli/templates/docker-compose.yml`

- [ ] **Step 1: Remove `container_name` fields and parameterize MySQL port**

Edit `src/agento/framework/cli/templates/docker-compose.yml`:

Remove these three lines (one from each service):
```
    container_name: agento-toolbox
```
```
    container_name: agento-cron
```
```
    container_name: agento-mysql
```

Change the MySQL port mapping from:
```yaml
    ports:
      - "3306:3306"
```
to:
```yaml
    ports:
      - "${MYSQL_PORT:-3306}:3306"
```

The final file should look like:

```yaml
name: agento

services:
  toolbox:
    build:
      context: ..
      dockerfile: docker/toolbox/Dockerfile
    image: agento-toolbox:latest
    environment:
      - TZ=${TZ:-UTC}
      - CRONDB_HOST=mysql
      - CRONDB_PORT=3306
      - CRONDB_DATABASE=cron_agent
      - CRONDB_USER=cron_agent
      - CRONDB_PASSWORD=${MYSQL_PASSWORD:-cronagent_pass}
    env_file:
      - path: ../secrets.env
        required: false
    volumes:
      - ../src/agento/toolbox:/app
      - /app/node_modules
      - ../src/agento/modules:/app/modules/core:ro
      - ../app/code:/app/modules/user:ro
      - ../logs:/app/logs
      - ../workspace/tmp:/workspace/tmp
    security_opt:
      - no-new-privileges:true
    networks:
      - agento-net
    depends_on:
      mysql:
        condition: service_healthy
    restart: unless-stopped

  cron:
    build:
      context: ..
      dockerfile: docker/cron/Dockerfile
    image: agento-cron:latest
    env_file:
      - path: ../secrets.env
        required: false
    environment:
      - TZ=${TZ:-UTC}
      - MYSQL_HOST=mysql
      - MYSQL_PORT=3306
      - MYSQL_DATABASE=cron_agent
      - MYSQL_USER=cron_agent
      - MYSQL_PASSWORD=${MYSQL_PASSWORD:-cronagent_pass}
      - DISABLE_LLM=${DISABLE_LLM:-0}
    volumes:
      - ../workspace:/workspace
      - ../app/code:/app/code:ro
      - ../logs:/app/logs
      - ../src/agento:/opt/cron-agent/src/agento
      - ../tokens:/etc/tokens
    networks:
      - agento-net
    depends_on:
      toolbox:
        condition: service_started
      mysql:
        condition: service_healthy
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    ports:
      - "${MYSQL_PORT:-3306}:3306"
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-cronagent_root}
      MYSQL_DATABASE: cron_agent
      MYSQL_USER: cron_agent
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-cronagent_pass}
    volumes:
      - ../storage/mysql:/var/lib/mysql
      - ../src/agento/framework/sql:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - agento-net
    restart: unless-stopped

networks:
  agento-net:
    driver: bridge
```

- [ ] **Step 2: Verify template is valid YAML**

Run: `uv run python -c "import yaml; yaml.safe_load(open('src/agento/framework/cli/templates/docker-compose.yml'))"`

If `yaml` not available, verify manually that the file has no syntax errors by inspection.

- [ ] **Step 3: Commit**

```bash
git add src/agento/framework/cli/templates/docker-compose.yml
git commit -m "feat: remove hardcoded container_name, parameterize MySQL port"
```

---

## Task 3: Update env template to renderable format

**Files:**
- Modify: `src/agento/framework/cli/templates/env.example`

- [ ] **Step 1: Replace env.example with renderable template**

Replace the entire contents of `src/agento/framework/cli/templates/env.example` with:

```
COMPOSE_PROJECT_NAME={compose_project_name}
MYSQL_ROOT_PASSWORD={mysql_root_password}
MYSQL_PASSWORD={mysql_password}
MYSQL_PORT={mysql_port}
TZ={timezone}
# Set to 1 to disable LLM API calls (mocks agent output, for testing)
DISABLE_LLM=0
```

- [ ] **Step 2: Commit**

```bash
git add src/agento/framework/cli/templates/env.example
git commit -m "feat: convert env.example to renderable template with placeholders"
```

---

## Task 4: Create install wizard — core helpers

**Files:**
- Create: `src/agento/framework/cli/install.py`
- Test: `tests/unit/framework/cli/test_install.py`

This task implements the pure helper functions (no I/O, no user prompts). Tasks 5–6 build on this.

- [ ] **Step 1: Write tests for helper functions**

```python
# tests/unit/framework/cli/test_install.py
"""Tests for agento install command."""
from __future__ import annotations

import re
import socket
from unittest.mock import patch

from agento.framework.cli.install import (
    _detect_timezone,
    _generate_password,
    _is_port_free,
    _sanitize_compose_name,
)


class TestSanitizeComposeName:
    def test_lowercase(self):
        assert _sanitize_compose_name("MyProject") == "myproject"

    def test_replaces_spaces(self):
        assert _sanitize_compose_name("My Project") == "my-project"

    def test_replaces_dots(self):
        assert _sanitize_compose_name("project.v2") == "project-v2"

    def test_replaces_underscores(self):
        assert _sanitize_compose_name("my_project") == "my-project"

    def test_strips_invalid_chars(self):
        assert _sanitize_compose_name("proj@#$ect") == "project"

    def test_collapses_hyphens(self):
        assert _sanitize_compose_name("a--b---c") == "a-b-c"

    def test_trims_leading_trailing_hyphens(self):
        assert _sanitize_compose_name("-project-") == "project"

    def test_fallback_to_agento(self):
        assert _sanitize_compose_name("___") == "agento"

    def test_empty_string(self):
        assert _sanitize_compose_name("") == "agento"

    def test_complex_example(self):
        assert _sanitize_compose_name("My Project.v2") == "my-project-v2"


class TestGeneratePassword:
    def test_returns_string(self):
        pw = _generate_password()
        assert isinstance(pw, str)
        assert len(pw) > 16

    def test_unique_per_call(self):
        assert _generate_password() != _generate_password()

    def test_url_safe_chars(self):
        pw = _generate_password()
        assert re.match(r'^[A-Za-z0-9_-]+$', pw), f"Password contains invalid chars: {pw}"


class TestIsPortFree:
    def test_free_port(self):
        # Port 0 always finds a free port, but let's use a high random one
        assert _is_port_free(0) is True

    def test_occupied_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            assert _is_port_free(port) is False


class TestDetectTimezone:
    def test_returns_string(self):
        tz = _detect_timezone()
        assert isinstance(tz, str)
        assert len(tz) > 0

    def test_fallback_to_utc(self):
        with patch("agento.framework.cli.install.Path") as mock_path:
            mock_path.return_value.resolve.side_effect = OSError("not found")
            tz = _detect_timezone()
            assert tz == "UTC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/framework/cli/test_install.py::TestSanitizeComposeName -v`
Expected: FAIL — `install` module does not exist yet.

- [ ] **Step 3: Implement helper functions**

Create `src/agento/framework/cli/install.py` with just the helpers for now:

```python
# src/agento/framework/cli/install.py
"""agento install — interactive project installation wizard."""
from __future__ import annotations

import re
import secrets
import socket
from pathlib import Path


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/framework/cli/test_install.py -v`
Expected: PASS (all helper tests)

- [ ] **Step 5: Commit**

```bash
git add src/agento/framework/cli/install.py tests/unit/framework/cli/test_install.py
git commit -m "feat(install): add core helper functions — sanitize, password, port check, tz detect"
```

---

## Task 5: Create install wizard — scaffolding logic

**Files:**
- Modify: `src/agento/framework/cli/install.py`
- Modify: `tests/unit/framework/cli/test_install.py`

- [ ] **Step 1: Write test for scaffolding**

Append to `tests/unit/framework/cli/test_install.py`:

```python
import json
from pathlib import Path

from agento.framework.cli.install import _scaffold


class TestScaffold:
    def test_creates_directory_structure(self, tmp_path: Path):
        config = {
            "compose_project_name": "test-proj",
            "mysql_root_password": "rootpass123",
            "mysql_password": "userpass456",
            "mysql_port": "3307",
            "timezone": "Europe/Warsaw",
        }
        _scaffold(tmp_path, "test-proj", config)

        assert (tmp_path / ".agento" / "project.json").is_file()
        assert (tmp_path / "app" / "code").is_dir()
        assert (tmp_path / "workspace" / "systems").is_dir()
        assert (tmp_path / "workspace" / "tmp").is_dir()
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "tokens").is_dir()
        assert (tmp_path / "storage").is_dir()
        assert (tmp_path / "docker").is_dir()
        assert (tmp_path / ".gitignore").is_file()
        assert (tmp_path / "secrets.env.example").is_file()

    def test_project_json_contents(self, tmp_path: Path):
        config = {
            "compose_project_name": "my-proj",
            "mysql_root_password": "rp",
            "mysql_password": "up",
            "mysql_port": "3306",
            "timezone": "UTC",
        }
        _scaffold(tmp_path, "my-proj", config)

        meta = json.loads((tmp_path / ".agento" / "project.json").read_text())
        assert meta["name"] == "my-proj"
        assert meta["version"] == "0.1.0"
        assert "created_at" in meta

    def test_env_file_rendered(self, tmp_path: Path):
        config = {
            "compose_project_name": "myapp",
            "mysql_root_password": "secret_root",
            "mysql_password": "secret_user",
            "mysql_port": "3307",
            "timezone": "America/New_York",
        }
        _scaffold(tmp_path, "myapp", config)

        env_content = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=myapp" in env_content
        assert "MYSQL_ROOT_PASSWORD=secret_root" in env_content
        assert "MYSQL_PASSWORD=secret_user" in env_content
        assert "MYSQL_PORT=3307" in env_content
        assert "TZ=America/New_York" in env_content
        assert "DISABLE_LLM=0" in env_content
        # No unresolved placeholders
        assert "{" not in env_content

    def test_docker_compose_has_no_container_name(self, tmp_path: Path):
        config = {
            "compose_project_name": "x",
            "mysql_root_password": "x",
            "mysql_password": "x",
            "mysql_port": "3306",
            "timezone": "UTC",
        }
        _scaffold(tmp_path, "x", config)

        compose = (tmp_path / "docker" / "docker-compose.yml").read_text()
        assert "container_name" not in compose
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/framework/cli/test_install.py::TestScaffold -v`
Expected: FAIL — `_scaffold` not defined yet.

- [ ] **Step 3: Implement `_scaffold` function**

Add to `src/agento/framework/cli/install.py`, after the existing helpers:

```python
import json
from datetime import UTC, datetime

from ._templates import get_template, TemplateNotFoundError


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

    # Docker Compose config
    try:
        compose_content = get_template("docker-compose.yml")
        (project_dir / "docker" / "docker-compose.yml").write_text(compose_content)
    except TemplateNotFoundError:
        pass

    # Render docker/.env from template
    try:
        env_template = get_template("env.example")
        env_content = env_template.format_map(config)
        (project_dir / "docker" / ".env").write_text(env_content)
    except TemplateNotFoundError:
        # Fallback: write basic env with provided config
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/framework/cli/test_install.py -v`
Expected: PASS (all tests including scaffold)

- [ ] **Step 5: Commit**

```bash
git add src/agento/framework/cli/install.py tests/unit/framework/cli/test_install.py
git commit -m "feat(install): add scaffolding logic with template rendering"
```

---

## Task 6: Create install wizard — interactive command

**Files:**
- Modify: `src/agento/framework/cli/install.py`
- Modify: `tests/unit/framework/cli/test_install.py`

- [ ] **Step 1: Write tests for the interactive wizard**

Append to `tests/unit/framework/cli/test_install.py`:

```python
import argparse
from unittest.mock import patch, MagicMock

from agento.framework.cli.install import InstallCommand


class TestInstallCommandAlreadyInstalled:
    def test_exits_if_project_json_exists(self, tmp_path: Path, capsys):
        (tmp_path / ".agento").mkdir()
        (tmp_path / ".agento" / "project.json").write_text('{"name":"x"}')

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            cmd = InstallCommand()
            cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        captured = capsys.readouterr()
        assert "already installed" in captured.out.lower()


class TestInstallCommandBasic:
    @patch("agento.framework.cli.install._run_post_install")
    @patch("agento.framework.cli.install.select", return_value=0)  # Basic
    @patch("builtins.input", return_value=".")
    def test_basic_install_scaffolds(self, mock_input, mock_select, mock_post, tmp_path: Path):
        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            cmd = InstallCommand()
            cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        assert (tmp_path / ".agento" / "project.json").is_file()
        assert (tmp_path / "docker" / ".env").is_file()

        env = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=" in env
        assert "MYSQL_ROOT_PASSWORD=" in env
        # Password should NOT be the old default
        assert "cronagent_pass" not in env
        assert "cronagent_root" not in env


class TestInstallCommandAdvanced:
    @patch("agento.framework.cli.install._run_post_install")
    @patch("agento.framework.cli.install._is_port_free", return_value=True)
    @patch("agento.framework.cli.install.select", return_value=1)  # Advanced
    @patch("builtins.input", side_effect=[".", "custom-name", "3307", "America/Chicago"])
    def test_advanced_install_uses_custom_values(self, mock_input, mock_select, mock_port, mock_post, tmp_path: Path):
        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            cmd = InstallCommand()
            cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        env = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=custom-name" in env
        assert "MYSQL_PORT=3307" in env
        assert "TZ=America/Chicago" in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/framework/cli/test_install.py::TestInstallCommandBasic -v`
Expected: FAIL — `InstallCommand` not defined yet.

- [ ] **Step 3: Implement `InstallCommand` and `_run_post_install`**

Add to `src/agento/framework/cli/install.py`, after the existing code. First add the import at the top of the file:

```python
import argparse
import subprocess
import sys

from ._output import cyan, log_error, log_info, log_warn
from .terminal import select
```

Then add these functions and class:

```python
def _run_post_install(project_dir: Path) -> None:
    """Run agento up + setup:upgrade after scaffolding."""
    from ._project import find_compose_file

    compose_file = find_compose_file(project_dir)
    if not compose_file:
        log_warn("docker-compose.yml not found. Skipping runtime startup.")
        return

    compose_cmd = ["docker", "compose", "-f", str(compose_file)]

    # Start containers
    log_info("Starting containers...")
    result = subprocess.run([*compose_cmd, "up", "-d"])
    if result.returncode != 0:
        log_error("Failed to start containers. Run 'agento up' manually.")
        return

    # Wait for MySQL
    import time

    log_info("Waiting for MySQL...")
    for _ in range(30):
        check = subprocess.run(
            [*compose_cmd, "exec", "-T", "mysql", "mysqladmin", "ping", "-h", "localhost", "--silent"],
            capture_output=True,
        )
        if check.returncode == 0:
            break
        time.sleep(2)
    else:
        log_warn("MySQL may not be ready yet. Continuing anyway...")

    # Run setup:upgrade
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/framework/cli/test_install.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/agento/framework/cli/install.py tests/unit/framework/cli/test_install.py
git commit -m "feat(install): implement interactive install wizard with basic/advanced modes"
```

---

## Task 7: Wire up CLI — register install, remove init, add auto-detect

**Files:**
- Modify: `src/agento/framework/cli/__init__.py`
- Delete: `src/agento/framework/cli/init.py`
- Delete: `tests/unit/framework/cli/test_init.py`

- [ ] **Step 1: Update `__init__.py` — replace init with install in `_LOCAL_COMMANDS`**

In `src/agento/framework/cli/__init__.py`, replace:

```python
_LOCAL_COMMANDS = frozenset({
    "doctor", "init", "up", "down", "logs",
    "module:list", "module:enable", "module:disable", "module:validate",
    "make:module",
    # Shortcuts for local commands
    "mo:li", "mo:en", "mo:di", "mo:va", "ma:mo",
})
```

with:

```python
_LOCAL_COMMANDS = frozenset({
    "doctor", "install", "up", "down", "logs",
    "module:list", "module:enable", "module:disable", "module:validate",
    "make:module",
    # Shortcuts for local commands
    "mo:li", "mo:en", "mo:di", "mo:va", "ma:mo",
})
```

- [ ] **Step 2: Update `_register_framework_commands` — swap InitCommand for InstallCommand**

Replace:

```python
    from .init import InitCommand
```

with:

```python
    from .install import InstallCommand
```

And in the list on line 94, replace `InitCommand` with `InstallCommand`:

```python
    for cmd_cls in [
        UpCommand, DownCommand, LogsCommand,
        DoctorCommand, InstallCommand,
        MakeModuleCommand, ModuleEnableCommand, ModuleDisableCommand, ModuleListCommand, ModuleValidateCommand,
        ConfigSetCommand, ConfigGetCommand, ConfigListCommand, ConfigRemoveCommand,
        ConsumerCommand, SetupUpgradeCommand, ReplayCommand, RotateCommand, E2eCommand,
        TokenRegisterCommand, TokenRefreshCommand, TokenListCommand, TokenDeregisterCommand, TokenSetCommand, TokenUsageCommand,
    ]:
```

- [ ] **Step 3: Update `_STANDALONE_GROUPS` — replace init with install**

Replace:

```python
_STANDALONE_GROUPS = {
    "doctor": "project", "init": "project", "up": "project",
    "down": "project", "logs": "project",
    "consumer": "job", "publish": "job", "replay": "job", "rotate": "job",
    "e2e": "test",
}
```

with:

```python
_STANDALONE_GROUPS = {
    "doctor": "project", "install": "project", "up": "project",
    "down": "project", "logs": "project",
    "consumer": "job", "publish": "job", "replay": "job", "rotate": "job",
    "e2e": "test",
}
```

- [ ] **Step 4: Update `_proxy_to_docker` error message**

Replace line 49:

```python
        print("Error: Not inside an agento project. Run 'agento init' first.", file=sys.stderr)
```

with:

```python
        print("Error: Not inside an agento project. Run 'agento install' first.", file=sys.stderr)
```

- [ ] **Step 5: Add auto-detect in `main()` — bare `agento` in non-project dir**

Replace lines 209-211:

```python
    if args.command is None:
        print(_format_help(commands))
        sys.exit(0)
```

with:

```python
    if args.command is None:
        from ._project import find_project_root
        from .terminal import select

        if find_project_root() is None:
            print()
            print("  Welcome to Agento \u2014 AI Agent Framework")
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
```

- [ ] **Step 6: Delete init.py and test_init.py**

```bash
git rm src/agento/framework/cli/init.py
git rm tests/unit/framework/cli/test_init.py
```

- [ ] **Step 7: Run full test suite to check for breakage**

Run: `uv run pytest -q`
Expected: PASS. Look for any imports of `init.py` that may have broken. If there are failures related to `init`, they need fixing (likely just import path updates).

- [ ] **Step 8: Commit**

```bash
git add src/agento/framework/cli/__init__.py
git commit -m "feat: wire up agento install, remove agento init, add auto-detect wizard"
```

---

## Task 8: Update compose.py error messages

**Files:**
- Modify: `src/agento/framework/cli/compose.py`

- [ ] **Step 1: Update error messages**

In `src/agento/framework/cli/compose.py`, replace line 17:

```python
        log_error("Not inside an agento project. Run 'agento init <project>' first.")
```

with:

```python
        log_error("Not inside an agento project. Run 'agento install' first.")
```

And replace line 21:

```python
        log_error("docker-compose.yml not found. Run 'agento init <project>' first.")
```

with:

```python
        log_error("docker-compose.yml not found. Run 'agento install' first.")
```

- [ ] **Step 2: Update `_project.py` docstring**

In `src/agento/framework/cli/_project.py`, replace the docstring comment on line 11:

```python
    1. .agento/project.json — created by `agento init`
```

with:

```python
    1. .agento/project.json — created by `agento install`
```

- [ ] **Step 3: Commit**

```bash
git add src/agento/framework/cli/compose.py src/agento/framework/cli/_project.py
git commit -m "chore: update error messages and docstrings from 'agento init' to 'agento install'"
```

---

## Task 9: Update CLAUDE.md with DX convention

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add DX convention to Key Conventions section**

In `CLAUDE.md`, after the line:

```
- **Events:** `agento_<area>_<action>` for framework events, `<vendor>_<module>_<event>` for third-party. Prefer domain/lifecycle events, not interception. See [docs/architecture/events.md](docs/architecture/events.md).
```

Add:

```
- **Interactive prompts:** Always use `terminal.select()` (arrow-key selection) for user choices. Never use Y/n text prompts. For text input (paths, port numbers), use `input()` with defaults shown in brackets.
```

- [ ] **Step 2: Update Essential Commands section — replace `agento init` with `agento install`**

In the Essential Commands section, replace:

```bash
agento init <project>                                  # Scaffold a new project
```

with:

```bash
agento install                                         # Interactive project installation wizard
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add arrow-key select DX convention, update init → install in CLAUDE.md"
```

---

## Task 10: Update docs/getting-started.md

**Files:**
- Modify: `docs/getting-started.md`

- [ ] **Step 1: Update the installation flow**

Replace lines 14-24:

```markdown
## Path A — Docker Compose (recommended)

```bash
# Install the CLI
uv tool install agento              # or: pip install agento

# Scaffold a new project
agento init my-project
cd my-project

# Start the runtime
agento up                            # Starts cron + toolbox + MySQL
agento setup:upgrade                 # Apply migrations, install crontab
```
```

with:

```markdown
## Path A — Docker Compose (recommended)

```bash
# Install the CLI
uv tool install agento              # or: pip install agento

# Create a project directory and install
mkdir my-project && cd my-project
agento install                       # Interactive wizard — scaffolds, starts, migrates
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/getting-started.md
git commit -m "docs: update getting-started to use agento install"
```

---

## Task 11: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -q`
Expected: PASS — all tests including new install tests.

- [ ] **Step 2: Check for any remaining `agento init` references in source code**

Run: `grep -r "agento init" src/ --include="*.py" -l`
Expected: no results (all references updated).

- [ ] **Step 3: Verify templates are valid**

Run:
```bash
uv run python -c "
from agento.framework.cli._templates import get_template
# Check env template renders without error
env = get_template('env.example')
rendered = env.format_map({
    'compose_project_name': 'test',
    'mysql_root_password': 'rp',
    'mysql_password': 'up',
    'mysql_port': '3306',
    'timezone': 'UTC',
})
assert '{' not in rendered, 'Unresolved placeholder!'
print('Templates OK')
# Check compose has no container_name
compose = get_template('docker-compose.yml')
assert 'container_name' not in compose, 'container_name still present!'
print('Compose OK')
"
```
Expected: "Templates OK" and "Compose OK"

- [ ] **Step 4: Verify CLI help shows `install` not `init`**

Run: `uv run agento --help`
Expected: Shows `install` under Project group, no `init`.
