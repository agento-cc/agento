# Agento

[![CI](https://github.com/agento-cc/agento/actions/workflows/ci.yml/badge.svg)](https://github.com/agento-cc/agento/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Self-hosted agent automation platform with modular integrations, Python execution runtime, Node.js toolbox, scoped config, and extension modules. Automates tasks using AI agents (Claude Code, OpenAI Codex) in Docker containers.

## Why Two Runtimes?

Agento enforces a strict security boundary between the AI sandbox and credentials. The sandbox where agents run has **zero access** to secrets. The toolbox is the only container that holds credentials, exposed via an MCP server that the agent calls through controlled tool interfaces.

```
┌───────────────────────────────────────────────────────┐
│                    Docker Network                     │
│                                                       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐  │
│  │   Sandbox   │   │   Toolbox   │   │     Cron    │  │
│  │   Claude/   │   │   Node.js   │   │    Python   │  │
│  │   Codex     │   │  MCP Server │   │   Consumer  │  │
│  │             │   │             │   │ + Scheduler │  │
│  │ NO secrets  │   │ Credentials │   │  Job Queue  │  │
│  └─────────────┘   └──────┬──────┘   └─────────────┘  │
│                           │                           │
│                     ┌─────┴─────┐                     │
│                     │   MySQL   │                     │
│                     └───────────┘                     │
└───────────────────────────────────────────────────────┘
```

## Quick Start

```bash
uv tool install agento-core           # Install the CLI
mkdir my-project && cd my-project
agento install                        # Interactive wizard — scaffolds, starts, migrates
```

## Architecture

Agento runs three Docker containers on a shared network:

- **Cron** (Python) -- Job queue consumer, scheduler, CLI host. Manages the lifecycle of agent jobs, runs migrations, and dispatches events. Connects to MySQL for job state, config, and module metadata.
- **Toolbox** (Node.js) -- MCP credential broker. Registers tools from modules (MySQL adapters, API clients) and exposes them over stdio. The only container with access to secrets.
- **Sandbox** (Claude Code / OpenAI Codex) -- Ephemeral container where the AI agent executes. Has no credentials, no direct database access. Communicates with the toolbox exclusively through MCP tool calls.

## Module System

Agento uses a Magento-inspired modular architecture. Each module is a self-contained package.

**Core modules** ship with the framework in `src/agento/modules/` (jira, claude, codex, core, crypt, agent_view).

**User modules** live in `app/code/` and are deployment-specific (gitignored by default).

Every module contains a `module.json` manifest and optional companion files:

| File | Purpose |
|------|---------|
| `module.json` | Module manifest (name, version, tools, knowledge) |
| `di.json` | Dependency injection configuration |
| `events.json` | Observer declarations for event-driven extensibility |
| `config.json` | Default config values with field metadata |
| `cron.json` | Scheduled job definitions |
| `sql/*.sql` | Schema migrations |
| `data_patch.json` | Data patches applied during setup |

**Config** follows a 3-level fallback: ENV vars (`CONFIG__MODULE__PATH`) take highest priority, then DB (`core_config_data`), then `config.json` defaults. Config can be scoped per agent_view for multi-tenant setups.

**Events** use an observer pattern. Modules declare observers in `events.json` and the framework dispatches events synchronously during lifecycle hooks (job start, job complete, schedule tick, etc.).

## Installation

### Docker Compose (recommended)

For end users, demos, PoC, and self-hosting:

```bash
uv tool install agento-core          # or: pip install agento-core
mkdir my-project && cd my-project
agento install                        # Interactive wizard — scaffolds, starts, migrates
```

The installer offers **Basic** (recommended) and **Advanced** modes. Basic uses sensible defaults. Advanced lets you configure Docker project name, MySQL port, and timezone for multi-instance setups.

### System check

```bash
agento doctor                         # Verify prerequisites
```

## Creating Your First Module

```bash
agento module:add my-app \
  --description="My application module" \
  --tool mysql:mysql_prod:"Production database (read-only)"
```

This creates a module in `app/code/my-app/` with a `module.json`, `config.json`, and `knowledge/` directory. Set credentials with:

```bash
agento config:set my_app/tools/mysql_prod/host 10.0.0.1
agento config:set my_app/tools/mysql_prod/pass secret123
```

See [Creating a Module](docs/modules/creating-a-module.md) for the full guide.

## Documentation

Full developer documentation is available in [docs/](docs/):

- [Getting Started](docs/getting-started.md) -- Install and create your first module
- [CLI Reference](docs/cli/) -- All `agento` commands
- [Module Guide](docs/modules/) -- Creating and managing modules
- [Config System](docs/config/) -- 3-level fallback, encryption, ENV vars
- [Architecture](docs/architecture/) -- Containers, zero-trust, job queue

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setting up a development environment, running tests, and submitting pull requests.

## License

MIT. See [LICENSE](LICENSE) for the full text.
