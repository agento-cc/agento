# Publisher-Consumer Pattern

Job queue architecture for automated task execution.

## Overview

```
Publisher (cron, every minute)
    │
    ├── jira-todo    → scan Jira for assigned TODO tasks
    ├── jira-cron    → fire scheduled recurring tasks
    └── jira-mention → detect @agent mentions in comments
    │
    ▼
MySQL (jobs table)
    │  INSERT IGNORE (idempotent)
    │
    ▼
Consumer (loop, poll every 5s)
    │  SELECT FOR UPDATE SKIP LOCKED
    │
    ▼
Runner (claude -p / codex exec)
    │
    ├── SUCCESS → mark complete, comment results on Jira
    ├── TODO    → retry with backoff (1m → 5m → 30m)
    └── DEAD    → max retries exhausted, mark dead
```

## Idempotency

Each job has a unique key preventing duplicates:

```
jira:{type}:{issue_key}:{time_window|comment_id}
```

`INSERT IGNORE` ensures the same task isn't queued twice within a time window.

## Job States

```
TODO → RUNNING → SUCCESS
                → TODO (retry)
                → DEAD (max retries)
```

| State | Description |
|-------|-------------|
| `TODO` | Queued, waiting for consumer |
| `RUNNING` | Claimed by consumer, executing |
| `SUCCESS` | Completed successfully |
| `DEAD` | Failed after max retries (3) |

## Retry Policy

- **Max attempts:** 3
- **Backoff:** exponential (1 min → 5 min → 30 min)
- **Non-retryable errors** → immediately DEAD (e.g., invalid issue key)

## Concurrency & Per-Run Isolation (Phase 9.5)

The consumer runs a bounded thread pool (`CONSUMER_MAX_WORKERS`). Each job gets an isolated run directory with freshly generated config files (`.claude.json`, `.mcp.json`, `AGENTS.md`, `SOUL.md`), eliminating the shared-file corruption that previously forced `concurrency=1`.

Jobs are dequeued by priority: `ORDER BY priority DESC, created_at ASC`. Priority is stamped at publish time from scoped config path `agent/scheduling/priority` (0-100, default 50).

Each job carries `agent_view_id` (resolved via ingress routing at publish time). The consumer resolves the agent_view's runtime profile (provider, model, scoped config) and generates per-run config files before CLI execution.

## Consumer Configuration

Configured via environment variables (set in `docker/.cron.env` or `docker-compose.yml`):

| Env Var | Default | Description |
|---------|---------|-------------|
| `CONSUMER_MAX_WORKERS` | 1 | Worker pool size (max concurrent jobs). Safe to increase with per-run isolation. |
| `CONSUMER_POLL_INTERVAL` | 5.0 | Seconds between poll cycles |
| `JOB_TIMEOUT_SECONDS` | 1200 | Max job runtime (20 min) |
| `DISABLE_LLM` | 0 | Dry-run mode (skip actual LLM calls) |
| `AGENTO_WORKSPACE_DIR` | /workspace | Base directory for per-run directories |

`CONSUMER_CONCURRENCY` is accepted as a backward-compatible alias for `CONSUMER_MAX_WORKERS`.

## Events

The consumer dispatches events at each state transition. Modules can observe these via `events.json` — see [Event-Observer System](events.md).

```
job_published  → job_claimed → job_succeeded
                             → job_failed → job_retrying
                             → job_failed → job_dead
```

## Source Files

| Component | File |
|-----------|------|
| Consumer loop | [src/agento/framework/consumer.py](../../src/agento/framework/consumer.py) |
| Publisher | [src/agento/framework/publisher.py](../../src/agento/framework/publisher.py) |
| Job models | [src/agento/framework/job_models.py](../../src/agento/framework/job_models.py) |
| Runner protocol | [src/agento/framework/runner.py](../../src/agento/framework/runner.py) |
| Event data classes | [src/agento/framework/events.py](../../src/agento/framework/events.py) |
