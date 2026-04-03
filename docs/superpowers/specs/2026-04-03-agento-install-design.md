# agento install — Unified Installation Wizard

## Context

Agento currently uses `agento init <dir>` which is non-interactive, always uses hardcoded defaults (`COMPOSE_PROJECT_NAME=agento`, default MySQL passwords, port 3306), and requires manual follow-up steps (`agento up`, `agento setup:upgrade`). This prevents running multiple Agento instances on the same host (port/name conflicts) and provides a poor first-run experience.

This spec replaces `agento init` with `agento install` — an interactive wizard with basic/advanced modes, auto-generated credentials, multi-instance support, and automatic runtime startup.

## Command Behavior

### `agento install`

Interactive wizard that scaffolds a project and starts the runtime. If `.agento/project.json` already exists, prints "Agento is already installed in this directory." and exits cleanly (exit 0).

### Bare `agento` (no args) in non-project directory

Auto-detects non-project directory via `find_project_root() → None`. Shows:

```
Welcome to Agento — AI Agent Framework
```

Then an arrow-key select:
- **Yes, set up a new project** → launches install wizard
- **No, show help** → prints normal CLI help

If inside an existing project, shows normal help as today.

### `agento init` — removed

Delete `init.py` entirely. Remove from command registration. Project is not public, no backward compat needed.

## Wizard Flow

### Step 1: Project Path

```
Project path [.]:
```

Text input with default `.` (current directory). Validation:
- Path must exist as a directory or be creatable
- If directory exists and is non-empty, error + re-prompt
- If path doesn't exist, create it (with `mkdir -p`)

### Step 2: Install Mode

Arrow-key select:
- **Basic (recommended)** — uses all defaults silently
- **Advanced** — prompts for additional configuration

### Step 3 (Advanced only): COMPOSE_PROJECT_NAME

```
Docker project name [<dir-name>]:
```

Text input. Default: sanitized directory name. Used by Docker Compose to prefix container names, networks, and volumes — enabling multiple instances.

**Sanitization** (applied to both the auto-generated default and user input):
1. Lowercase
2. Replace spaces, dots, underscores with hyphens
3. Strip characters not matching `[a-z0-9-]`
4. Collapse consecutive hyphens into one
5. Trim leading/trailing hyphens
6. If result is empty after sanitization, fall back to `"agento"`

Examples: `"My Project.v2"` → `"my-project-v2"`, `"Agento Test"` → `"agento-test"`, `"___"` → `"agento"`.

### Step 4 (Advanced only): MySQL Port

```
MySQL host port [3306]:
```

Text input. Default: `3306`. Validation:
- Must be a valid port number (1–65535)
- Check if port is free via `socket.bind("127.0.0.1", port)`. If taken, error + re-prompt.

### Step 5 (Advanced only): Timezone

```
Timezone [Europe/Warsaw]:
```

Text input. Default: auto-detected from system. Detection strategy:
1. Parse `/etc/localtime` symlink → extract Olson name after `zoneinfo/` (works on macOS + Linux)
2. Fallback: `"UTC"`

### Always (both modes):

- **MySQL passwords**: auto-generated via `secrets.token_urlsafe(24)` — separate root and user passwords. Written to `docker/.env`, never displayed to user.
- **Basic mode defaults**: COMPOSE_PROJECT_NAME = sanitized dir name, MySQL port = 3306, TZ = auto-detected

## Post-Scaffold

After writing all files, the wizard automatically:
1. Runs `agento up` (starts Docker Compose)
2. Waits for MySQL healthcheck
3. Runs `agento setup:upgrade` (applies migrations, installs crontab, runs module onboarding)
4. Prints success message with next steps

## Files Created (Scaffold)

```
<project>/
├── .agento/
│   └── project.json          # { name, version: "0.1.0", created_at }
├── app/
│   └── code/                 # User modules
├── workspace/
│   ├── systems/
│   └── tmp/
├── logs/
├── tokens/
├── storage/
├── docker/
│   ├── docker-compose.yml    # From template (no container_name fields)
│   └── .env                  # Rendered with install config
├── .gitignore                # From template
└── secrets.env.example       # From template
```

## Docker Template Changes

### `templates/docker-compose.yml`

- **Remove** all `container_name` fields (toolbox, cron, mysql). Docker Compose auto-generates names using `COMPOSE_PROJECT_NAME` prefix (e.g., `myproject-mysql-1`).
- **Parameterize** MySQL port: `"${MYSQL_PORT:-3306}:3306"`

### `templates/env.example` → rendered template

Template with `{placeholders}` rendered via `str.format_map()`:

```
COMPOSE_PROJECT_NAME={compose_project_name}
MYSQL_ROOT_PASSWORD={mysql_root_password}
MYSQL_PASSWORD={mysql_password}
MYSQL_PORT={mysql_port}
TZ={timezone}
# Set to 1 to disable LLM API calls (mocks agent output, for testing)
DISABLE_LLM=0
```

## File Changes

| File | Action | Details |
|------|--------|---------|
| `cli/install.py` | **Create** | Full install wizard: InstallCommand class + helper functions |
| `cli/_templates.py` | **Create** | Extract `_get_template()` + `TemplateNotFoundError` from init.py |
| `cli/init.py` | **Delete** | No backward compat needed |
| `cli/__init__.py` | **Modify** | Register InstallCommand, remove init, add auto-detect in main(), update `_LOCAL_COMMANDS`, update error messages |
| `cli/compose.py` | **Modify** | Update "Run 'agento init' first" → "Run 'agento install' first" |
| `templates/docker-compose.yml` | **Modify** | Remove container_name, parameterize MySQL port |
| `templates/env.example` | **Modify** | Add placeholders for rendering |
| `docs/getting-started.md` | **Modify** | Reference `agento install` |
| `CLAUDE.md` | **Modify** | Add DX convention: use arrow-key select() for all user prompts, never Y/n |

## Key Implementation Details

### InstallCommand structure (`cli/install.py`)

```
InstallCommand              # Command class (name="install")
├── execute(args)           # Entry point — orchestrates flow
├── _ask_project_path()     # Prompt + validation loop
├── _ask_install_mode()     # terminal.select() → basic/advanced
├── _sanitize_compose_name() # Lowercase, strip invalid chars, collapse hyphens
├── _ask_compose_name()     # Text input with sanitized default
├── _ask_mysql_port()       # Text input + port-free validation loop
├── _ask_timezone()         # Text input with auto-detected default
├── _detect_timezone()      # Parse /etc/localtime symlink
├── _is_port_free(port)     # socket.bind() check
├── _generate_password()    # secrets.token_urlsafe(24)
├── _scaffold(config)       # Create dirs + render files
└── _run_post_install()     # agento up + setup:upgrade
```

### Compose name sanitization

```python
import re

def _sanitize_compose_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[\s._]+", "-", name)
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name or "agento"
```

Applied to both the default (derived from dir name) and any user-typed value in advanced mode. If the sanitized result differs from user input, show what it was sanitized to.

### Template rendering

Use `str.format_map()` — zero dependencies, sufficient for 6 variables, no conditionals needed in templates. Only `env.example` needs rendering; `docker-compose.yml` is copied as-is (uses `${VAR}` syntax resolved by Docker Compose at runtime).

### Password generation

```python
secrets.token_urlsafe(24)  # 32-char URL-safe string
```

Two separate calls for root and user passwords.

### Port validation

```python
import socket

def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
```

### Timezone detection

```python
def _detect_timezone() -> str:
    try:
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        idx = parts.index("zoneinfo")
        return "/".join(parts[idx + 1:])
    except (ValueError, OSError):
        return "UTC"
```

## DX Convention (add to CLAUDE.md)

**Interactive prompts**: Always use `terminal.select()` (arrow-key selection) for user choices. Never use Y/n text prompts. For text input (paths, port numbers), use `input()` with defaults shown in brackets.

## Verification

1. **Fresh install (basic)**:
   ```bash
   mkdir /tmp/test-agento && cd /tmp/test-agento
   agento install
   # Select "." path, "Basic" mode
   # Verify: docker/.env has random passwords, COMPOSE_PROJECT_NAME=test-agento
   # Verify: Docker containers running, MySQL healthy, setup:upgrade completed
   ```

2. **Fresh install (advanced)**:
   ```bash
   mkdir /tmp/test-agento2 && cd /tmp/test-agento2
   agento install
   # Select "." path, "Advanced" mode
   # Set custom compose name, port 3307, verify timezone default
   # Verify: docker/.env has custom values
   # Verify: MySQL on port 3307
   ```

3. **Multi-instance**: Run two installs in different directories with different compose names and ports. Verify both run simultaneously without conflicts.

4. **Already installed**: Run `agento install` in an existing project → prints "already installed", exits 0.

5. **Bare `agento`**: Run `agento` with no args outside a project → shows welcome + select prompt.

6. **Port conflict**: Try installing with a port already in use → error message, re-prompt.

7. **Run tests**: `uv run pytest -q` — all existing + new tests pass.
