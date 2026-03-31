# CLI Reference

`agento` is the main CLI (like Magento's `bin/magento`). Install via `uv tool install agento` or `pip install agento`.

## Command Reference

| Command | Description |
|---------|-------------|
| **Project Lifecycle** | |
| `doctor` | Check system prerequisites ([details](doctor.md)) |
| `init <project>` | Scaffold a new project ([details](init.md)) |
| `up` | Start Docker Compose runtime |
| `down` | Stop Docker Compose runtime |
| `logs [service]` | Show container logs |
| **Setup** | |
| `setup:upgrade [--dry-run]` | Apply migrations, data patches, install crontab |
| `reindex` | Reindex modules → workspace/systems/ + AGENTS.md |
| **Modules** | |
| `module:add <name>` | Add a module ([details](modules.md)) |
| `module:list` | List installed modules |
| `module:remove <name>` | Remove a module |
| `make:module <name>` | Scaffold a new module (Python) |
| `module:validate [name]` | Validate module structure |
| **Config** | |
| `config:set <path> <value> [--scope=S] [--scope-id=N]` | Set config override in DB ([details](config.md)) |
| `config:get <path\|module>` | Get config value (exact path or module tree view) |
| `config:list [prefix]` | List config values (all scopes) |
| `config:remove <path> [--scope=S] [--scope-id=N]` | Remove config override from DB |
| **Tokens** | |
| `token register <agent> <label> [path]` | Register OAuth token ([details](tokens.md)) |
| `token list` | List tokens with usage stats |
| `token set <agent> <id>` | Set primary token |
| `token refresh <id>` | Re-authenticate token |
| `token deregister <id>` | Disable token |
| `token usage` | Show token usage |
| `rotate` | Rotate active tokens |
| **Ingress** | |
| `ingress:bind <type> <value> <agent_view>` | Bind inbound identity to agent_view |
| `ingress:list [--type <type>] [--json]` | List all identity bindings |
| `ingress:unbind <type> <value>` | Remove identity binding |
| **Operations** | |
| `consumer` | Start job consumer loop |
| `jira:periodic:sync` | Sync Jira recurring tasks to crontab |
| `publish <kind>` | Publish a job (jira-cron, jira-todo, jira-mention) |
| `jira:periodic:exec <key>` | Execute a recurring task |
| `exec:todo [key]` | Execute next TODO task |
| `replay <job_id>` | Replay a completed job |
| `e2e` | Run end-to-end tests |

## How It Works

`agento` is a Python console_script installed via `uv tool install agento` or `pip install agento`. Standalone commands (doctor, init, up/down/logs) work without a database. Runtime commands (consumer, config, token) require MySQL.

For development convenience, `bin/agento` delegates to `uv run agento`.

Source: [src/agento/framework/cli/](../../src/agento/framework/cli/)
