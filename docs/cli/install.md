# bin/agento install

Full installation command. Generates config, builds Docker images, starts containers, runs migrations.

## Usage

```bash
bin/agento install \
  --agent-email=agent@mycompany.com \
  --jira-host=https://mycompany.atlassian.net \
  --jira-projects=AI,DEV \
  --agent-role="Senior Developer" \
  --timezone=Europe/Warsaw
```

## Parameters

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--agent-email` | Yes | — | Agent email (used as MCP tool credential) |
| `--jira-host` | Yes | — | Jira instance URL |
| `--jira-projects` | Yes | — | Jira project keys (comma-separated) |
| `--agent-role` | No | "Senior Developer" | Agent role in SOUL.md |
| `--jira-assignee` | No | same as agent-email | Jira assignee email |
| `--jira-assignee-id` | No | — | Jira account ID |
| `--jira-status` | No | "To Do" | Status name for recurring tasks |
| `--jira-frequency-field` | No | customfield_10709 | Custom field ID for cron frequency |
| `--timezone` | No | UTC | Container timezone |
| `--skip-build` | No | — | Skip Docker image build |

## What It Does (Step by Step)

1. Validates prerequisites (docker, docker compose)
2. Creates directories (workspace/systems/, logs/, tokens/)
3. Generates `workspace/SOUL.md` from template
4. Generates `docker/.cron.env` with module config (`CONFIG__JIRA__*` entries)
5. Generates `AGENTS.md` from template + installed modules
6. Checks/copies `secrets.env` from template
7. Generates `AGENTO_ENCRYPTION_KEY` in secrets.env (if missing)
8. Adds `JIRA_HOST` to secrets.env (if missing)
9. Builds Docker images
10. Starts containers (`docker compose up -d cron`)
11. Waits for MySQL, runs migrations
12. Runs reindex

## Generated Files

| File | Template | Description |
|------|----------|-------------|
| `workspace/SOUL.md` | `workspace/SOUL.md.template` | Agent identity (email, role) |
| `docker/.cron.env` | — | Module config env vars (`CONFIG__JIRA__*`) |
| `workspace/AGENTS.md` | `workspace/AGENTS.md.template` | Agent instructions (tools, KB) |
