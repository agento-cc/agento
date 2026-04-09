# agento install

Interactive project installation wizard. Scaffolds a new project, starts Docker containers, runs migrations, and sets up an agent provider.

## Usage

```bash
agento install
```

No command-line flags — everything is collected interactively.

## Interactive Steps

### 1. Project Path

Prompts for the project directory (default: current directory `.`). The directory must be empty or non-existent (created automatically).

### 2. Existing Project Check

If `.agento/project.json` is found, the wizard offers a **reinstall** option. Reinstall refreshes framework files while preserving data:

| Preserved | Refreshed |
|-----------|-----------|
| `storage/` (MySQL data) | `docker-compose.yml` |
| `tokens/` | `docker/sql/` (migrations) |
| `secrets.env` | `AGENTO_VERSION` in `docker/.env` |
| `app/code/` (user modules) | `.agento/project.json` version |
| `workspace/` | |

### 3. Installation Mode

Choose between **Basic (recommended)** and **Advanced**. Basic uses sensible defaults; Advanced lets you customize:

| Setting | Basic Default | Advanced |
|---------|--------------|----------|
| Docker project name | Sanitized from directory name | Prompted |
| MySQL host port | `3306` | Prompted (with port availability check) |
| Timezone | Auto-detected from `/etc/localtime` | Prompted |

### 4. Scaffolding

Creates the project directory structure:

```
project/
├── .agento/project.json
├── .gitignore
├── app/code/
├── docker/
│   ├── docker-compose.yml
│   ├── .env
│   └── sql/
├── logs/
├── secrets.env
├── secrets.env.example
├── storage/
├── tokens/
└── workspace/
    ├── systems/
    └── tmp/
```

Auto-generates:
- `AGENTO_ENCRYPTION_KEY` (32-byte hex) in `secrets.env`
- MySQL root and user passwords (random URL-safe tokens)

### 5. Post-Install

1. Starts Docker containers (`docker compose up -d`)
2. Waits for the cron container's initial `setup:upgrade` (migrations, data patches)
3. Runs interactive `setup:upgrade` (module onboarding)
4. Prompts for AI agent provider selection (Claude, Codex) and token registration

## Generated Files

| File | Description |
|------|-------------|
| `.agento/project.json` | Project metadata (name, version, creation date) |
| `.gitignore` | Default ignore patterns for agento projects |
| `docker/docker-compose.yml` | Docker Compose configuration (from package template) |
| `docker/.env` | Compose env vars (project name, version, MySQL credentials, port, timezone) |
| `docker/sql/*.sql` | Schema migration scripts (extracted from package) |
| `secrets.env` | Encryption key (auto-generated, not committed) |
| `secrets.env.example` | Template showing required secret variables |

Source: `src/agento/framework/cli/install.py`
