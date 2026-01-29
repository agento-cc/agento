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

Event names encode ownership so the source is obvious from the string itself:

- **Framework events (legacy):** `job_failed`, `module_ready`, `consumer_started` — short names, kept for backward compatibility.
- **Framework events (new):** `agento_<area>_<action>` — e.g. `agento_config_saved`, `agento_setup_complete`. The `agento_` prefix marks framework-owned events.
- **Third-party module events:** `<vendor>_<module>_<event>` — e.g. `acme_slack_message_sent`. Vendor prefix prevents collisions across modules.

## Core Events

### Job Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `job_published` | `JobPublishedEvent` | `type, source, reference_id, idempotency_key` | After job inserted into queue |
| `job_claimed` | `JobClaimedEvent` | `job` | After job dequeued (status → RUNNING) |
| `job_succeeded` | `JobSucceededEvent` | `job, summary, agent_type, model, elapsed_ms` | After SUCCESS commit |
| `job_failed` | `JobFailedEvent` | `job, error, elapsed_ms` | On any failure (fires before retry/dead) |
| `job_retrying` | `JobRetryingEvent` | `job, error, delay_seconds, elapsed_ms` | After retry scheduled (status → TODO) |
| `job_dead` | `JobDeadEvent` | `job, error, elapsed_ms` | After max retries exhausted (status → DEAD) |

`job_failed` fires on every failure, then one of `job_retrying` or `job_dead` also fires.

### Consumer Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `consumer_started` | `ConsumerStartedEvent` | *(none)* | Consumer main loop begins |
| `consumer_stopping` | `ConsumerStoppingEvent` | *(none)* | Consumer begins graceful shutdown |

### Module Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `module_register` | `ModuleRegisterEvent` | `name, path, config` | Module loaded, before capabilities |
| `module_loaded` | `ModuleLoadedEvent` | `name, path` | After capabilities registered |
| `module_ready` | `ModuleReadyEvent` | `name, path` | All modules loaded, safe to query registries |
| `module_shutdown` | `ModuleShutdownEvent` | `name, path` | Graceful shutdown (reverse dependency order) |

### Config & Setup Lifecycle

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `agento_config_saved` | `ConfigSavedEvent` | `path, encrypted` | After CLI `config:set` commits a value |
| `agento_setup_before` | `SetupBeforeEvent` | `dry_run` | Before `setup:upgrade` begins work |
| `agento_setup_complete` | `SetupCompleteEvent` | `result, dry_run` | After `setup:upgrade` finishes all work |
| `agento_migration_applied` | `MigrationAppliedEvent` | `version, module, path` | After a SQL migration is applied |
| `agento_data_patch_applied` | `DataPatchAppliedEvent` | `name, module` | After a data patch is applied |
| `agento_crontab_installed` | `CrontabInstalledEvent` | `job_count` | After crontab is updated (not on dry-run) |

### Worker Pool Lifecycle (Phase 9.5)

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `agento_worker_started` | `WorkerStartedEvent` | `worker_slot, job_id` | Worker slot begins processing a job |
| `agento_worker_stopped` | `WorkerStoppedEvent` | `worker_slot, job_id, elapsed_ms` | Worker slot finishes processing |
| `agento_agent_view_run_started` | `AgentViewRunStartedEvent` | `job, agent_view_id, provider, model, priority, run_dir` | Before CLI execution (after config files generated) |
| `agento_agent_view_run_finished` | `AgentViewRunFinishedEvent` | `job, agent_view_id, provider, model, elapsed_ms, success` | After CLI execution completes |

`agento_agent_view_run_started` fires after per-run config files are generated but before the CLI subprocess starts. The `agent_view` module observes this event to write `AGENTS.md` and `SOUL.md` into the run directory.

### Routing

| Event | Data Class | Fields | When |
|-------|-----------|--------|------|
| `agento_routing_resolved` | `RoutingResolvedEvent` | `context, agent_view_id, matched_router, reason, candidate_count` | After routing resolves to an agent_view |
| `agento_routing_ambiguous` | `RoutingAmbiguousEvent` | `context, agent_view_id, matched_router, all_routers, reason` | When multiple routers match (first wins) |
| `agento_routing_failed` | `RoutingFailedEvent` | `context` | When no router matches the inbound identity |

`agento_routing_ambiguous` still resolves (first router wins by order), but flags the ambiguity for observability.

### Config & Setup Lifecycle

`agento_config_saved` fires only from CLI `config:set`, not from internal bootstrap config resolution.

`agento_crontab_installed` fires only when the crontab actually changed and not during dry-run.

## Event Data Mutability

Event data objects are **mutable** — observers can modify fields. Execution order is deterministic via the `order` field, so earlier observers can enrich data for later ones.

## Bootstrap Sequence

```
1. Clear all registries
2. Resolve module order (topological sort)
3. Resolve configs (3-level fallback)
4. For each module (dependency order):
   a. Load observers from events.json
   b. Dispatch module_register
   c. Load channels, workflows, runtimes from di.json
   d. Dispatch module_loaded
5. For each module: dispatch module_ready
```

Shutdown dispatches `module_shutdown` in **reverse** dependency order.

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
| Example observers | [app/code/_example/src/observers.py](../../app/code/_example/src/observers.py) |

## When to Add an Event

- **Add** when a module might reasonably want to react to a state change (e.g., config saved, migration applied, job completed).
- **Prefer domain/lifecycle events** — `agento_config_saved` (something happened) over `agento_config_before_save` (intercept before it happens). No generic `before_save` / `after_load` magic.
- **Don't add** events for internal operations that modules should not interfere with (e.g., registry clearing during bootstrap).
- **Don't add** generic before/after hooks on every function — events should be at meaningful extension points.
- **Events stay synchronous** — keep debugging and ordering simple.
