# Event-Observer System

Magento-style event-observer pattern for cross-module communication. Modules subscribe to events without direct coupling.

## How It Works

1. **Framework dispatches events** at key lifecycle points (job state changes, module loading, consumer start/stop)
2. **Modules declare observers** in `events.json` — classes with an `execute(event)` method
3. **Bootstrap wires observers** to events from each module's `events.json`
4. **Observers execute synchronously** in deterministic order (by `order` field, then name)
5. **Errors are swallowed** — a failing observer never crashes job processing

## Observer Class

```python
class MyJobFailedObserver:
    def execute(self, event):
        # event is a mutable dataclass — fields depend on event type
        logger.warning("Job %d failed: %s", event.job.id, event.error)
```

Import contracts from `agento.framework.contracts` for type hints:

```python
from agento.framework.contracts import JobFailedEvent

class MyJobFailedObserver:
    def execute(self, event: JobFailedEvent) -> None:
        ...
```

## events.json

Declare observers per event in your module's `events.json` (like Magento's `events.xml`):

```json
{
  "job_failed": [
    {
      "name": "mymodule_job_failed",
      "class": "src.observers.MyJobFailedObserver",
      "order": 100
    }
  ],
  "job_succeeded": [
    {
      "name": "mymodule_job_succeeded",
      "class": "src.observers.MyJobSucceededObserver"
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique observer name (convention: `{module}_{event}`) |
| `class` | Yes | Dotted path to observer class relative to module dir |
| `order` | No | Execution priority (default 1000, lower = earlier) |

## Event Naming Convention

All event names follow a strict pattern: **`{subject}_{verb}_{before|after}`**

- **`subject`** — the entity or concept: `job`, `consumer`, `module`, `worker`, `config`, `routing`, `workspace_build`, `skill_sync`
- **`verb`** — what happens: `claim`, `fail`, `succeed`, `start`, `stop`, `save`, `load`, `resolve`
- **`before|after`** — timing relative to the action:
  - `_before` — fires before the action completes (observers can inspect but not prevent)
  - `_after` — fires after the action is committed

Examples: `job_claim_after`, `module_register_before`, `workspace_build_complete_after`

**Third-party module events** use: `{vendor}_{module}_{subject}_{verb}_{before|after}` — e.g. `acme_slack_message_send_after`. Vendor prefix prevents collisions.

## Core Events

### Job Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `job_publish_after` | `JobPublishedEvent` | `type, source, reference_id, idempotency_key` | After job inserted into queue |
| `job_claim_after` | `JobClaimedEvent` | `job` | After job dequeued (status → RUNNING) |
| `job_succeed_after` | `JobSucceededEvent` | `job, summary, agent_type, model, elapsed_ms` | After SUCCESS commit |
| `job_fail_after` | `JobFailedEvent` | `job, error, elapsed_ms` | On any failure (fires before retry/dead) |
| `job_retry_after` | `JobRetryingEvent` | `job, error, delay_seconds, elapsed_ms` | After retry scheduled (status → TODO) |
| `job_dead_after` | `JobDeadEvent` | `job, error, elapsed_ms` | After max retries exhausted (status → DEAD) |

`job_fail_after` fires on every failure, then one of `job_retry_after` or `job_dead_after` also fires.

### Consumer Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `consumer_start_after` | `ConsumerStartedEvent` | *(none)* | Consumer main loop begins |
| `consumer_stop_before` | `ConsumerStoppingEvent` | *(none)* | Consumer begins graceful shutdown |

### Module Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `module_register_before` | `ModuleRegisterEvent` | `name, path, config` | Module loaded, before capabilities |
| `module_load_after` | `ModuleLoadedEvent` | `name, path` | After capabilities registered |
| `module_ready_after` | `ModuleReadyEvent` | `name, path` | All modules loaded, safe to query registries |
| `module_shutdown_before` | `ModuleShutdownEvent` | `name, path` | Graceful shutdown (reverse dependency order) |

### Config & Setup Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `config_save_after` | `ConfigSavedEvent` | `path, encrypted` | After CLI `config:set` commits a value |
| `setup_upgrade_before` | `SetupBeforeEvent` | `dry_run` | Before `setup:upgrade` begins work |
| `setup_upgrade_after` | `SetupCompleteEvent` | `result, dry_run` | After `setup:upgrade` finishes all work |
| `migration_apply_after` | `MigrationAppliedEvent` | `version, module, path` | After a SQL migration is applied |
| `data_patch_apply_after` | `DataPatchAppliedEvent` | `name, module` | After a data patch is applied |
| `crontab_install_after` | `CrontabInstalledEvent` | `job_count` | After crontab is updated (not on dry-run) |

### Worker Pool Lifecycle (Phase 9.5)

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `worker_start_after` | `WorkerStartedEvent` | `worker_slot, job_id` | Worker slot begins processing a job |
| `worker_stop_after` | `WorkerStoppedEvent` | `worker_slot, job_id, elapsed_ms` | Worker slot finishes processing |
| `agent_view_run_start_before` | `AgentViewRunStartedEvent` | `job, agent_view_id, provider, model, priority, run_dir` | Before CLI execution (after config files generated) |
| `agent_view_run_finish_after` | `AgentViewRunFinishedEvent` | `job, agent_view_id, provider, model, elapsed_ms, success` | After CLI execution completes |

`agent_view_run_start_before` fires after per-run config files are generated but before the CLI subprocess starts. The `agent_view` module observes this event to write `AGENTS.md` and `SOUL.md` into the run directory.

### Routing

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `routing_resolve_after` | `RoutingResolvedEvent` | `context, agent_view_id, matched_router, reason, candidate_count` | After routing resolves to an agent_view |
| `routing_ambiguous_after` | `RoutingAmbiguousEvent` | `context, agent_view_id, matched_router, all_routers, reason` | When multiple routers match (first wins) |
| `routing_fail_after` | `RoutingFailedEvent` | `context` | When no router matches the inbound identity |

`routing_ambiguous_after` still resolves (first router wins by order), but flags the ambiguity for observability.

### Workspace Build Lifecycle (Phase 10.5a)

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `workspace_build_start_after` | `WorkspaceBuildStartedEvent` | `agent_view_id, build_id` | After build record inserted (status → building) |
| `workspace_build_complete_after` | `WorkspaceBuildCompletedEvent` | `agent_view_id, build_id, build_dir, checksum, skipped` | After build succeeds (status → ready) or skipped (identical checksum) |
| `workspace_build_fail_after` | `WorkspaceBuildFailedEvent` | `agent_view_id, build_id, error` | After build fails (status → failed) |

`workspace_build_complete_after` fires both for new builds and for skipped builds (when `skipped=True`, the checksum matched an existing ready build). The `skipped` flag lets observers distinguish the two cases.

### Skill Lifecycle (Phase 10.5a)

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `skill_sync_complete_after` | `SkillSyncCompletedEvent` | `skills_dir, new, updated, unchanged` | After `skill:sync` finishes scanning disk and updating DB |

`skill_sync_complete_after` fires after the DB commit in `sync_skills()`. Observers can use it to trigger workspace rebuilds when skill content changes (Phase 10.5b).

### Config & Setup Lifecycle

`config_save_after` fires only from CLI `config:set`, not from internal bootstrap config resolution.

`crontab_install_after` fires only when the crontab actually changed and not during dry-run.

## Event Data Mutability

Event data objects are **mutable** — observers can modify fields. Execution order is deterministic via the `order` field, so earlier observers can enrich data for later ones.

## Bootstrap Sequence

```
1. Clear all registries
2. Resolve module order (topological sort)
3. Resolve configs (3-level fallback)
4. For each module (dependency order):
   a. Load observers from events.json
   b. Dispatch module_register_before
   c. Load channels, workflows, runtimes from di.json
   d. Dispatch module_load_after
5. For each module: dispatch module_ready_after
```

Shutdown dispatches `module_shutdown_before` in **reverse** dependency order.

## Source Files

| Component | File |
|-----------|------|
| EventManager | [src/agento/framework/event_manager.py](../../src/agento/framework/event_manager.py) |
| Event data classes | [src/agento/framework/events.py](../../src/agento/framework/events.py) |
| Bootstrap wiring | [src/agento/framework/bootstrap.py](../../src/agento/framework/bootstrap.py) |
| Consumer dispatch | [src/agento/framework/consumer.py](../../src/agento/framework/consumer.py) |
| Publisher dispatch | [src/agento/framework/publisher.py](../../src/agento/framework/publisher.py) |
| Setup dispatch | [src/agento/framework/setup.py](../../src/agento/framework/setup.py) |
| Migration dispatch | [src/agento/framework/migrate.py](../../src/agento/framework/migrate.py) |
| Data patch dispatch | [src/agento/framework/data_patch.py](../../src/agento/framework/data_patch.py) |
| CLI dispatch | [src/agento/framework/cli.py](../../src/agento/framework/cli.py) |
| Router dispatch | [src/agento/framework/router.py](../../src/agento/framework/router.py) |
| Builder dispatch | [src/agento/modules/workspace_build/src/builder.py](../../src/agento/modules/workspace_build/src/builder.py) |
| Skill registry dispatch | [src/agento/modules/skill/src/registry.py](../../src/agento/modules/skill/src/registry.py) |
| Example observers | [app/code/_example/src/observers.py](../../app/code/_example/src/observers.py) |

## When to Add an Event

- **Add** when a module might reasonably want to react to a state change (e.g., `config_save_after`, `migration_apply_after`, `job_succeed_after`).
- **Prefer `_after` events** — most events fire after the action is committed. Use `_before` only when observers need to inspect state before it changes (e.g., `consumer_stop_before`, `module_shutdown_before`).
- **Don't add** events for internal operations that modules should not interfere with (e.g., registry clearing during bootstrap).
- **Don't add** generic before/after hooks on every function — events should be at meaningful extension points.
- **Events stay synchronous** — keep debugging and ordering simple.
