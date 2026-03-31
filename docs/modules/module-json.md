# module.json

Module manifest — declares metadata, tools, and field schemas. Read by Toolbox at startup.

## Full Schema

```json
{
  "name": "my-ecommerce",
  "version": "1.0.0",
  "description": "My e-commerce platform",
  "repo": "git@github.com:org/my-ecommerce.git",
  "tools": [
    {
      "type": "mysql",
      "name": "mysql_ecom_prod",
      "description": "Production MySQL (read-only). Tables: orders, products, customers.",
      "fields": {
        "host":     {"type": "string",  "label": "Host"},
        "port":     {"type": "integer", "label": "Port", "default": 3306},
        "user":     {"type": "string",  "label": "User"},
        "pass":     {"type": "obscure", "label": "Password"},
        "database": {"type": "string",  "label": "Database"}
      }
    }
  ],
  "log_servers": [
    {
      "name": "app-server",
      "host": "log_reader@app.example.com",
      "apps": ["my-ecommerce", "redis"]
    }
  ]
}
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Module identifier (used in config paths, directory name) |
| `version` | No | Semantic version |
| `description` | Yes | Human-readable description (shown in `module:list`) |
| `sequence` | No | Array of module names this module depends on (Magento `<sequence>`). Dependencies load first. Default: `[]` |
| `order` | No | Integer sort position within same dependency tier — lower loads earlier. Default: `1000` |
| `repo` | No | Git repository URL for source code access |
| `tools` | No | Array of tool definitions |
| `log_servers` | No | SSH log servers for the AI agent |

## Tool Definition

| Field | Description |
|-------|-------------|
| `type` | Adapter type: `mysql`, `mssql`, `opensearch` |
| `name` | Globally unique tool name (registered as MCP tool) |
| `description` | Shown to the AI agent — include table names, data types |
| `fields` | Config field schemas (see below) |

## Field Types

| Type | Description | Encrypted in DB? |
|------|-------------|-------------------|
| `string` | Plain text value | No |
| `integer` | Numeric value | No |
| `obscure` | Sensitive value (password, token) | Yes (AES-256-CBC) |

Fields with `"default"` are used as the lowest-priority fallback if no ENV, DB, or config.json value exists.

## Companion Files

Magento-style separation — each concern has its own JSON file:

| File | Purpose | Magento Equivalent |
|------|---------|-------------------|
| `di.json` | Channel, workflow, runtime class bindings | `di.xml` |
| `system.json` | Config field schemas with types and labels | `system.xml` |
| `events.json` | Event observer declarations | `events.xml` |
| `config.json` | Default config values (non-secret) | `config.xml` |
| `data_patch.json` | Data patch declarations (seeding, data transforms) | `DataPatchInterface` |
| `cron.json` | Cron job declarations (scheduled CLI commands) | `crontab.xml` |
| `sql/*.sql` | Schema migrations (numbered, sequential) | `db_schema.xml` / setup scripts |

### toolbox/ directory

JS files in `toolbox/` are auto-discovered by the Toolbox container at startup. Each file must export `register(server, context)`. The `context` provides `{ app, log, db, playwright }`.

```
my-module/
  toolbox/
    my-tool.js      # exports register(server, context) — auto-discovered
    api.js           # REST API routes — also auto-discovered
```

See [src/agento/modules/jira/toolbox/](../../src/agento/modules/jira/toolbox/) for a complete example with MCP tools and REST routes.

### di.json

Registers capabilities your module provides — channels, workflows, runtimes, CLI commands. Bootstrap reads this and populates the corresponding registries.

```json
{
  "channels": [
    {"name": "jira", "class": "src.channel.JiraChannel"}
  ],
  "workflows": [
    {"type": "cron", "class": "src.workflows.cron.CronWorkflow"},
    {"type": "todo", "class": "src.workflows.todo.TodoWorkflow"}
  ],
  "runtimes": [
    {"provider": "claude", "class": "src.runner.TokenClaudeRunner"}
  ],
  "commands": [
    {"name": "sync", "class": "src.commands.sync.SyncCommand"},
    {"name": "publish", "class": "src.commands.publish.PublishCommand"}
  ]
}
```

Each section is optional — include only what your module provides.

| Section | Key Fields | Registry |
|---------|-----------|----------|
| `channels` | `name`, `class` | Channel registry — `get_channel(name)` |
| `workflows` | `type`, `class` | Workflow registry — `get_workflow_class(AgentType)` |
| `runtimes` | `provider`, `class` | Runner factory — `create_runner(AgentProvider)` |
| `commands` | `name`, `class` | CLI command registry — adds `bin/agento <name>` subcommand |

Class paths are dotted relative to the module directory: `src.channel.JiraChannel` resolves to `<module>/src/channel.py` → `JiraChannel`.

### system.json

Declares config fields your module needs, with types and labels. The framework resolves values through the [3-level fallback](../config/README.md) (ENV → DB → config.json). Default values belong in `config.json`.

```json
{
  "toolbox_url": {"type": "string", "label": "Toolbox URL"},
  "user": {"type": "string", "label": "AI User"},
  "api_token": {"type": "obscure", "label": "API Token"},
  "max_results": {"type": "integer", "label": "Max results"},
  "project_list": {"type": "json", "label": "Projects (JSON array)"}
}
```

Field types: `string`, `integer`, `boolean`, `json`, `obscure` (encrypted in DB).

Resolved config is available at runtime via `get_module_config("module_name")` — returns a `dict[str, Any]`.

### events.json

Declares observers that react to framework events. See [Event-Observer System](../architecture/events.md) for full event list.

```json
{
  "job_failed": [
    {
      "name": "mymodule_job_failed",
      "class": "src.observers.JobFailedObserver",
      "order": 100
    }
  ]
}
```

Observer classes must implement `execute(event)`:

```python
class JobFailedObserver:
    def execute(self, event):
        # event.job, event.error, event.elapsed_ms
        logger.warning("Job %d failed: %s", event.job.id, event.error)
```

### data_patch.json

Declares data patches — Python classes that seed or transform data. Applied by `setup:upgrade` in topological order (respecting `require()` dependencies). Tracked in the `data_patch` table.

```json
{
    "patches": [
        {"name": "SeedDefaults", "class": "src.patches.seed_defaults.SeedDefaults"}
    ]
}
```

Patch classes implement the `DataPatch` protocol (import from `agento.framework.contracts`):

```python
from agento.framework.contracts import DataPatch

class SeedDefaults:
    def apply(self, conn):
        with conn.cursor() as cur:
            cur.execute("INSERT IGNORE INTO config ...")
        conn.commit()

    def require(self):
        # Fully-qualified names: "module/PatchName"
        return []  # No dependencies
```

`require()` returns a list of patch names that must run first (Magento's `getDependencies()`). Names use `module/PatchName` format.

### cron.json

Declares scheduled CLI commands. Collected by `setup:upgrade` into the `AGENTO:BEGIN/END` crontab block. Separate from dynamic cron blocks (e.g. Jira's `JIRA-SYNC:BEGIN/END` for per-issue entries).

```json
{
    "jobs": [
        {"name": "sync", "schedule": "0 * * * *", "command": "sync"},
        {"name": "publish_todo", "schedule": "* * * * *", "command": "publish jira-todo"}
    ]
}
```

`command` is the CLI subcommand name — the framework wraps it with environment loading and Docker paths. Module authors don't need to know about container internals.

### sql/ directory

Numbered SQL migration files, applied by `setup:upgrade` in module dependency order. Same convention as framework migrations.

```
my-module/
  sql/
    001_create_custom_table.sql
    002_add_index.sql
```

Tracked in the `schema_migration` table with a `module` column distinguishing framework from module migrations.

### CLI Commands

Modules contribute CLI subcommands via the `commands` section in `di.json`. Command classes implement the `Command` protocol:

```python
import argparse

class SyncCommand:
    @property
    def name(self) -> str:
        return "sync"

    @property
    def help(self) -> str:
        return "Sync recurring tasks to crontab"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def execute(self, args: argparse.Namespace) -> None:
        # Your command logic here
        ...
```

After bootstrap, the command appears as `bin/agento sync --dry-run`. Framework commands (consumer, setup:upgrade, config, token, rotate) are built-in; module commands extend the CLI dynamically.

## Reference

See [app/code/_example/](../../app/code/_example/) for a working example with observers.

See [src/agento/modules/jira/](../../src/agento/modules/jira/) for a complete core module with channels, workflows, and commands.
