# Tool Commands

List, enable, and disable MCP tools per agent_view using scoped config. Tools are registered via module manifests (`module.json`).

## `tool:list`

### Usage

```bash
# List all tools (global status)
agento tool:list

# List tools with status scoped to an agent_view
agento tool:list --agent-view developer
```

Shortcut: `to:li`

### Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--agent-view <code>` | No | — | Show enabled/disabled status for this agent_view |

### Output

```
  jira_search                    jira                 enabled
  jira_create                    jira                 disabled
  slack_post                     slack                enabled
  browser                        core                 enabled
```

Columns: tool name, module name, status. Tools are **enabled by default** — disabled only when `tools/{name}/is_enabled` is explicitly set to `0`.

## `tool:enable`

### Usage

```bash
# Enable at default scope
agento tool:enable jira_search

# Enable for a specific agent_view
agento tool:enable jira_search --agent-view developer

# Enable at explicit scope
agento tool:enable jira_search --scope workspace --scope-id 1
```

Shortcut: `to:en`

### Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `tool_name` | Yes | — | Name of the tool (must be snake_case) |
| `--agent-view <code>` | No | — | Shortcut for `--scope agent_view` (resolves code → ID) |
| `--scope` | No | `default` | Config scope: `default`, `workspace`, `agent_view` |
| `--scope-id` | No | `0` | Scope ID |

### What It Does

Sets `tools/{name}/is_enabled = 1` in scoped config (`core_config_data` table).

**Validation**: `tool_name` must be snake_case — lowercase letters, digits, and underscores only, starting with a letter (`^[a-z][a-z0-9_]*$`). Names with spaces, uppercase, or special characters are rejected.

## `tool:disable`

### Usage

```bash
agento tool:disable jira_search
agento tool:disable jira_search --agent-view developer
```

Shortcut: `to:di`

### Options

Same as `tool:enable`.

### What It Does

Sets `tools/{name}/is_enabled = 0` in scoped config.

## How Tool Config Works

### Tool Registration

Tools are declared in each module's `module.json` under the `tools` array. At bootstrap, the framework loads all module manifests and registers their tools. `tool:list` reads from these manifests.

### Scoped Config

Enable/disable uses the standard 3-level scoped config system:

- Config path: `tools/{name}/is_enabled`
- Value: `1` (enabled) or `0` (disabled)
- Scopes: `default` → `workspace` → `agent_view` (most specific wins)

Tools are enabled by default — no config entry needed. Only explicitly disabled tools are filtered out.

### The `--agent-view` Shortcut

The `--agent-view <code>` flag resolves the agent_view code to `scope=agent_view, scope_id=<agent_view.id>`. It's equivalent to `--scope agent_view --scope-id <id>` but more convenient since you don't need to look up the numeric ID.

### Toolbox Integration

The toolbox uses the same `isToolEnabled` mechanism to filter which MCP tools are exposed to the agent CLI at runtime. Disabling a tool removes it from the agent's available tool set for that agent_view.

Source: `src/agento/modules/agent_view/src/commands/tool_list.py`, `tool_enable.py`, `tool_disable.py`
