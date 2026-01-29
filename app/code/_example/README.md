# Example Module

This is the golden path example for creating an Agento module. Copy this directory to start your own module:

```bash
cp -r app/code/_example app/code/my-module
```

Or use the CLI:

```bash
bin/agento make:module my-module --description "My custom module"
```

## Directory Structure

| File | Purpose |
|------|---------|
| `module.json` | Module manifest -- name, version, tools, log servers |
| `config.json` | Default config values (overridable via ENV or DB) |
| `di.json` | Dependency injection -- registers channels, workflows, commands |
| `events.json` | Event observers -- react to framework and module events |
| `system.json` | Config field schema -- defines types and labels for config fields |
| `data_patch.json` | Data patches -- one-time data migrations |
| `cron.json` | Cron jobs -- scheduled tasks |
| `knowledge/` | Module-specific documentation and context for AI agents |
| `src/` | Python source code -- commands, channels, workflows, observers |

## How It Works

1. **Commands** are registered via `di.json` and follow the `Command` protocol (see `src/commands/hello.py`)
2. **Config** uses 3-level fallback: ENV (`CONFIG__MODULE__FIELD`) -> DB -> `config.json`
3. **Events** let you react to lifecycle events without modifying other modules
4. **Tools** define external service connections (MySQL, MSSQL, OpenSearch)

See [docs/modules/creating-a-module.md](../../docs/modules/creating-a-module.md) for the full guide.
