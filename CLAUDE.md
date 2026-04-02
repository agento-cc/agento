# Agento — AI Agent Framework

Automates Jira tasks using AI agents (Claude Code, OpenAI Codex) in Docker containers with Magento-inspired modular architecture.

## Core Principles

1. **Simplicity over complexity.** Simplest solution that works is the best. Three similar lines > premature abstraction.
2. **Encapsulation, SOLID, DRY.** Clear boundaries. Dependencies through protocols, not concretes. Testable in isolation.
3. **TDD where possible.** Red → green → refactor. Unit tests with mocks (respx/pytest).
4. **Surgical changes.** Only what's necessary. No extra comments, docstrings, type hints in untouched code.
5. Utilize Framework features for new implementations:
    - Event-observers
    - 3-level system config fallback
    - (more in docs/)

## Key Conventions

- **Python:** httpx (not requests), dataclasses (not Pydantic), PyMySQL (not mysql-connector)
- **Tests:** pytest + respx, fixtures in `tests/fixtures/`
- **CLI:** `bin/agento <command>` — Magento-like CLI
- **Core modules:** `src/agento/modules/<name>/` with `module.json` — ship with framework
- **User modules:** `app/code/<name>/` with `module.json` + `config.json` — per-deployment, gitignored
- **Config:** 3-level fallback: ENV (`CONFIG__MODULE__PATH`) → DB (`core_config_data`) → `config.json`. Per-agent_view scoped config via `scope='agent_view'` in DB.
- **Concurrent execution:** `CONSUMER_MAX_WORKERS` env var (default 1). Per-run isolation makes it safe to increase.
- **Routing:** Ingress identities map inbound requests to agent_views. Channels auto-resolve via `resolve_agent_view()` before publishing.
- **Agent view config:** Scoped DB paths `agent/provider`, `agent/claude/model`, `agent/scheduling/priority`, `agent/instructions/agents_md`, `agent/instructions/soul_md` — resolved with agent_view → workspace → global fallback.
- **Security:** Toolbox = only container with secrets. Agent has NO credentials.
- **DB tables:** singular names (e.g., `job`, `schedule`, `oauth_token`). Exception: `core_config_data` (Magento convention).
- **Setup:** `setup:upgrade` on deploy — applies schema migrations, data patches, installs crontab, runs module onboarding (strict: complete, disable+dependents, or quit). Use `--skip-onboarding` for CI/CD. Manual alternative: pre-set config values via `config:set`. See [docs/cli/onboarding.md](docs/cli/onboarding.md).
- **Module setup files:** `sql/*.sql` (schema migrations), `data_patch.json` (data patches), `cron.json` (cron jobs), `di.json` onboarding (interactive external system setup)
- **Migration tracking:** `schema_migration` table (with `module` column), `data_patch` table
- **Events:** `agento_<area>_<action>` for framework events, `<vendor>_<module>_<event>` for third-party. Prefer domain/lifecycle events, not interception. See [docs/architecture/events.md](docs/architecture/events.md).
- **Logs:** consumer → JSON structured, publisher/sync → text. Never delete while consumer runs.
- **Code via volume mounts** — after changes: `docker compose restart cron` (Python) or `docker compose restart toolbox` (JS). Rebuild only for dependency changes (`pyproject.toml` / `package.json`).

## Essential Commands

```bash
# Tests (all: JSON validation + Python + JS)
bin/test

# Or individually:
uv run pytest -q                                       # Python (~756 tests, from repo root)
cd src/agento/toolbox && npm test && cd -              # JS (vitest, from repo root)

# Project lifecycle
agento doctor                                          # Check prerequisites
agento init <project>                                  # Scaffold a new project
agento up                                              # Start Docker Compose
agento down                                            # Stop containers
agento logs [service]                                  # View container logs

# Restart after code changes
cd docker && docker compose restart cron toolbox

# Full rebuild (dependency changes only)
cd docker && docker compose build cron toolbox && docker compose up -d --force-recreate

# Setup (after module changes or deploy)
agento setup:upgrade                                   # Apply migrations, data patches, install crontab, run onboarding
agento setup:upgrade --dry-run                         # Preview pending work
agento setup:upgrade --skip-onboarding                 # Skip interactive module onboarding (for CI/CD)

# Modules
agento module:add <name> --tool mysql:<tool_name>:<description>
agento module:list                                     # List all modules with enabled/disabled status
agento module:enable <name>                            # Enable a module (stored in app/etc/modules.json)
agento module:disable <name>                           # Disable a module (skips loading, cron, config, CLI)
agento module:validate [name]                          # Validate module structure and sequence deps
agento reindex

# Config
agento config:set <path> <value> [--scope=<scope>] [--scope-id=<id>]
agento config:get <path>                               # exact path: per-scope values
agento config:get <module>                             # module prefix: tree view by scope
agento config:list [prefix]
agento config:remove <path> [--scope=<scope>] [--scope-id=<id>]

# Tokens
agento token:list
agento token:register claude <label> [path]
agento token:set claude <id>

# Ingress identity binding (route inbound requests to agent_views)
agento ingress:bind <type> <value> <agent_view_code>   # e.g. ingress:bind jira jira developer
agento ingress:list [--type <type>] [--json]
agento ingress:unbind <type> <value>
```

## Documentation

Full developer documentation in [docs/](docs/):

- [Getting Started](docs/getting-started.md) — install + first module in 5 minutes
- [CLI Reference](docs/cli/) — all `agento` commands
- [Modules Guide](docs/modules/) — creating and managing modules
- [Config System](docs/config/) — 3-level fallback, encryption, ENV vars
- [Tool Adapters](docs/tools/) — built-in + creating custom adapters
- [Architecture](docs/architecture/) — containers, zero-trust, job queue

## Strategic Decisions

Architectural and technical decisions (why httpx, why PyMySQL, idempotency design, etc.) are documented in [DECISIONS.md](DECISIONS.md). Add new decisions there when making non-obvious technical choices.

## Additional References

- [docker/README.md](docker/README.md) — Docker deployment, auth, Playwright setup
- [docker/cron/app/README.md](docker/cron/app/README.md) — Docker cron container internals
- [ROADMAP.md](ROADMAP.md) — framework evolution roadmap
