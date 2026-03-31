# Jira Agent

Python application that automates Jira task execution using Claude Code, with a MySQL-backed job queue for reliable scheduling.

> For framework-level documentation (modules, config, CLI), see [docs/](../../../docs/).

## Architecture

```
cron (every minute)
  ├── jira:periodic:sync → queries Jira, updates crontab, syncs schedules table
  ├── publish      → inserts jobs into MySQL queue (publisher)
  │
consumer (long-running loop)
  └── dequeue      → SELECT FOR UPDATE SKIP LOCKED → execute via Runner
        ├── success  → status = SUCCESS
        ├── retry    → status = TODO (with backoff delay)
        └── dead     → status = DEAD (non-retryable or max attempts)
```

**Publisher-consumer pattern:**
- **Publishers** produce jobs into the MySQL `jobs` table (Jira publisher is first; email publisher planned)
- **Consumer** dequeues and executes jobs via a configurable Runner (subprocess calling `claude -p` or `codex exec`)
- Crontab never executes agents directly — it only publishes jobs

**CLI commands** (`agent`):
- `jira:periodic:sync` — queries Jira for periodic task issues, updates crontab + schedules table
- `publish jira-cron <issue_key>` — publish a recurring task job
- `publish jira-todo [issue_key]` — publish a TODO task job (or dispatch)
- `consumer` — start the job consumer loop
- `jira:periodic:exec` / `exec:todo` — direct execution (bypass queue, for debugging)
- `task-list` — show prioritized action list
- `token register <agent_type> <label> [credentials_path] [--token-limit N]` — register a subscription token (omit path for interactive OAuth)
- `token list [--agent-type claude|codex] [--all] [--json]` — list registered tokens
- `token deregister <token_id>` — disable a token (soft-delete)
- `token usage [--agent-type claude|codex] [--window N]` — show token usage stats
- `rotate` — rotate active tokens for all agent types based on remaining capacity
- `migrate [--dry-run]` — apply pending database migrations (tracked in `schema_migrations` table)

## File Structure

```
app/
  pyproject.toml          # uv project: httpx + PyMySQL runtime, pytest+respx dev
  uv.lock
  src/                    # Python package
    __init__.py
    cli.py                # CLI entry point — argparse with sync/publish/consumer/exec subcommands
    config.py             # Loads cron.json + MySQL env vars into CronConfig dataclass
    log.py                # Structured JSON logging with custom formatter for consumer output
    models.py             # Domain models: JiraIssue, TaskAction, TaskPriority, TaskSource enums
    toolbox_client.py     # HTTP client for toolbox REST API (Jira search proxy)
    runner.py             # RunResult dataclass + Runner Protocol (provider-agnostic)
    runner_factory.py     # create_runner() factory for provider selection (lazy imports)
    claude_runner.py      # Runs Claude CLI as subprocess and parses JSON result with token stats
    crontab.py            # Manages crontab entries with JIRA-SYNC markers for safe updates
    lock.py               # mkdir-based file lock with stale lock detection
    # Periodic task sync and execution moved to jira_periodic_tasks module
    # See: src/agento/modules/jira_periodic_tasks/
    exec_todo_task.py     # Executes a one-time TODO Jira task via Claude (6-step workflow)
    task_list.py          # Builds prioritized action list from 7 Jira query angles
    db.py                 # MySQL connection factory using PyMySQL with DictCursor
    migrate.py            # Schema migration runner with version tracking (schema_migrations table)
    job_models.py         # AgentType (CRON/TODO), JobStatus enums, and Job dataclass
    publisher.py          # Generic publish() — idempotent INSERT IGNORE into jobs table
    jira_publisher.py     # Jira-specific publisher with time-windowed idempotency keys
    consumer.py           # Job consumer loop with ThreadPoolExecutor and retry/dead-letter
    retry_policy.py       # Retry classification + exponential backoff (1m, 5m, 30m)
    agent_manager/          # Multi-token orchestration sub-package
      models.py             # AgentProvider enum, Token, UsageSummary, RotationResult
      config.py             # AgentManagerConfig frozen dataclass
      token_store.py        # CRUD for tokens table
      usage_store.py        # record_usage(), get_usage_summary()
      active.py             # Atomic symlink: resolve, update, read_credentials
      rotator.py            # select_best_token(), rotate_tokens(), rotate_all()
      runner.py             # TokenRunner ABC (Template Method pattern)
      claude_runner.py      # TokenClaudeRunner (subscription-managed Claude)
      codex_runner.py       # TokenCodexRunner (subscription-managed Codex)
      auth.py               # Interactive OAuth auth (isolated HOME, browser flow)
    sql/
      001_create_tables.sql   # DDL for schedules + jobs tables (auto-loaded by MySQL)
      005_agent_manager.sql   # DDL for tokens + usage_log tables
  tests/
    conftest.py           # Shared fixtures and sample CronConfig
    fixtures/             # Mocked Jira JSON responses for tests
    test_*.py             # Unit tests for each module
```

## Agent Manager (Multi-Token Rotation)

Manages multiple subscription tokens per agent type (Claude, Codex) with hourly rotation based on remaining capacity.

**Providers** (`provider` in `cron.json` or `PROVIDER` env var):
- `claude_oauth` — default, uses existing OAuth credentials
- `claude_subscription` — token-managed Claude runner with subscription keys
- `codex_subscription` — token-managed Codex runner with subscription keys

**Credentials** are JSON files mounted at `/etc/tokens/`:
```json
{"subscription_key": "sk-ant-..."}
```

**Usage:**
```bash
# Register tokens (interactive OAuth — launches browser auth)
agent token register claude prod-1
agent token register codex prod-1

# Register tokens (with existing credentials file)
agent token register claude prod-1 /etc/tokens/claude_1.json --token-limit 1000000
agent token register claude prod-2 /etc/tokens/claude_2.json --token-limit 1000000

# List tokens
agent token list
agent token list --agent-type claude --json

# Check usage
agent token usage --window 24

# Rotate (picks token with most remaining capacity)
agent rotate

# Disable a token
agent token deregister 2
```

**Rotation algorithm:** selects the token with the highest remaining capacity (`token_limit - tokens_used`). Unlimited tokens (`token_limit=0`) are always preferred. Tie-break: fewer total calls wins.

## Setup

1. Set `jira_assignee` in `cron.json` (email of the AI Jira user, e.g. `agenty@example.com`)
2. Set `user` in `cron.json` (human owner email, used as fallback)
3. Ensure `JIRA_USER` and `JIRA_TOKEN` are set in `secrets.env` (used by toolbox, not by cron)
4. Optionally set `MYSQL_PASSWORD` in `secrets.env` (default: `cronagent_pass`)
5. Build and start:

```bash
cd docker
docker compose build cron
docker compose up -d cron    # starts cron + consumer + mysql
```

## Running Tests

```bash
cd docker/cron/app
uv run --group dev pytest -v
```

## Supported Frequencies

| Jira Value | Cron Schedule |
|---|---|
| Co 5min | `*/5 * * * *` |
| Co 30min | `*/30 * * * *` |
| Co 1h | `0 * * * *` |
| Co 4h | `0 */4 * * *` |
| 1x dziennie o 8:00 | `0 8 * * *` |
| 1x dziennie o 1:00 w nocy | `0 1 * * *` |
| 2x dziennie o 6:00 i 18:00 | `0 6,18 * * *` |
| 1x w tygodniu (Pon, 7:00) | `0 7 * * 1` |

## Monitoring

```bash
# Check current crontab inside container
docker compose exec cron crontab -u agent -l

# View logs
tail -f logs/sync-jira-cron.log     # Sync: Jira queries, crontab updates
tail -f logs/publisher.log          # Publisher: job enqueue events
tail -f logs/consumer.log           # Consumer: job execution (structured JSON)

# Preview sync without modifying crontab
docker compose exec cron /opt/cron-agent/run.sh jira:periodic:sync --dry-run

# Show prioritized task list
docker compose exec cron /opt/cron-agent/run.sh task-list --json

# Query job queue directly
docker compose exec mysql mysql -u cron_agent -pcronagent_pass cron_agent \
  -e "SELECT id, type, source, reference_id, status, attempt, created_at FROM jobs ORDER BY id DESC LIMIT 10;"

# Token management
docker compose exec cron /opt/cron-agent/run.sh token list --json
docker compose exec cron /opt/cron-agent/run.sh token usage --window 24
docker compose exec cron /opt/cron-agent/run.sh rotate
```
