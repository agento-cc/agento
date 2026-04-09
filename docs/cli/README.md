# CLI Reference

`agento` is the main CLI (like Magento's `bin/magento`). Install via `uv tool install agento-core`.

## Command Reference

| Command | Description |
|---------|-------------|
| **Project Lifecycle** | |
| `doctor` | Check system prerequisites ([details](doctor.md)) |
| `install` | Install a new project — interactive wizard ([details](install.md)) |
| `upgrade [--version X.Y.Z]` | Upgrade Docker images to match CLI version ([details](upgrade.md)) |
| `up` | Start Docker Compose runtime |
| `down` | Stop Docker Compose runtime |
| `logs [service]` | Show container logs |
| **Setup** | |
| `setup:upgrade [--dry-run] [--skip-onboarding]` | Apply migrations, data patches, install crontab, run onboarding ([onboarding details](onboarding.md)) |
| `reindex` | Reindex modules → workspace/systems/ + AGENTS.md |
| **Modules** | |
| `module:add <name>` | Add a module ([details](modules.md)) |
| `module:list` | List installed modules |
| `module:enable <name>` | Enable a module |
| `module:disable <name>` | Disable a module |
| `module:validate [name]` | Validate module structure |
| `module:remove <name>` | Remove a module |
| **Config** | |
| `config:set <path> <value> [--scope=S] [--scope-id=N]` | Set config override in DB ([details](config.md)) |
| `config:get <path\|module>` | Get config value (exact path or module tree view) |
| `config:list [prefix]` | List config values (all scopes) |
| `config:remove <path> [--scope=S] [--scope-id=N]` | Remove config override from DB |
| **Tokens** | |
| `token:register <agent> <label> [path]` | Register OAuth token ([details](tokens.md)) |
| `token:list` | List tokens with usage stats |
| `token:set <agent> <id>` | Set primary token |
| `token:refresh <id>` | Re-authenticate token |
| `token:deregister <id>` | Disable token |
| `token:usage` | Show token usage |
| `rotate` | Rotate active tokens |
| **Ingress** | |
| `ingress:bind <type> <value> <agent_view>` | Bind inbound identity to agent_view |
| `ingress:list [--type <type>] [--json]` | List all identity bindings |
| `ingress:unbind <type> <value>` | Remove identity binding |
| **Tools** | |
| `tool:list [--agent-view <code>]` | List registered tools with enabled/disabled status ([details](tools.md)) |
| `tool:enable <name> [--agent-view <code>]` | Enable a tool at given scope ([details](tools.md)) |
| `tool:disable <name> [--agent-view <code>]` | Disable a tool at given scope ([details](tools.md)) |
| **Skills** | |
| `skill:sync` | Scan skills from disk and sync to registry ([details](skills.md)) |
| `skill:list [--agent-view <code>]` | List registered skills with status ([details](skills.md)) |
| `skill:enable <name> [--agent-view <code>]` | Enable a skill at given scope ([details](skills.md)) |
| `skill:disable <name> [--agent-view <code>]` | Disable a skill at given scope ([details](skills.md)) |
| **Workspace** | |
| `workspace:build --agent-view <code> \| --all` | Build materialized workspace ([details](workspace-build.md)) |
| `workspace:build-status [--agent-view <code>]` | Show workspace build history ([details](workspace-build.md)) |
| **Operations** | |
| `consumer` | Start job consumer loop |
| `jira:periodic:sync` | Sync Jira recurring tasks to crontab |
| `publish <kind>` | Publish a job (jira-cron, jira-todo, jira-mention) |
| `jira:periodic:exec <key>` | Execute a recurring task |
| `exec:todo [key]` | Execute next TODO task |
| `replay <job_id>` | Replay a completed job |
| `e2e` | Run end-to-end tests |

## How It Works

`agento` is a Python console_script installed via `uv tool install agento-core`. Standalone commands (doctor, install, upgrade, up/down/logs) work without a database. Runtime commands (consumer, config, token) require MySQL.

For development convenience, `bin/agento` delegates to `uv run agento`.

Source: [src/agento/framework/cli/](../../src/agento/framework/cli/)
