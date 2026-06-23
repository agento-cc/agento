# MCP Tools

Tools are exposed to the AI agent via MCP (Model Context Protocol). The Toolbox serves two transports: SSE at `/sse` (used by Claude) and streamable HTTP at `/mcp` (used by Codex). The Toolbox discovers and registers tools from modules at startup.

## Architecture

```
Agent (cron/sandbox)                    Toolbox
┌─────────────┐    MCP/SSE    ┌─────────────────────────┐
│ Claude CLI   │◄────────────►│ MCP Server (:3001)      │
│ reads .mcp.json             │                         │
│                             │ ┌─────────────────────┐ │
│                             │ │ config-loader.js    │ │
│                             │ │ scans modules/core  │ │
│                             │ │ + modules/user      │ │
│                             │ └─────────┬───────────┘ │
│                             │           │             │
│                             │ ┌─────────▼───────────┐ │
│                             │ │ Adapter Tools       │ │
│                             │ │ (mysql, mssql,      │ │
│                             │ │  opensearch)        │ │
│                             │ ├─────────────────────┤ │
│                             │ │ Module Tools        │ │
│                             │ │ (jira, email,       │ │
│                             │ │  schedule, browser) │ │
│                             │ └─────────────────────┘ │
└─────────────┘               └─────────────────────────┘
```

## Two Types of Tools

### Module Tools (from toolbox/ directories)

Discovered by convention from `<module>/toolbox/*.js` files. Each file exports a `register(server, context)` function.

**Core module** (`src/agento/modules/core/toolbox/`):

| Tool | Description |
|------|-------------|
| `email_send` | SMTP email (whitelisted recipients) |
| `schedule_followup` | Schedule future task execution |
| `browser_navigate`, `browser_screenshot`, etc. | Playwright browser |

**Jira module** (`src/agento/modules/jira/toolbox/`):

| Tool | Description |
|------|-------------|
| `jira_search`, `jira_get_issue`, `jira_add_comment`, `jira_get_attachment` (opt-in), etc. | Jira Cloud integration |

**Outlook module** (`src/agento/modules/outlook/toolbox/`):

| Tool | Description |
|------|-------------|
| `outlook_get_message`, `outlook_search_messages`, `outlook_get_new_messages`, `outlook_reply`, `outlook_send_mail`, `outlook_mark_processed` | Microsoft 365 / Graph email channel (opt-in; sender/recipient allow-listed). See [outlook.md](../modules/outlook.md). |

**User modules** (`app/code/<name>/toolbox/`):

Custom JS tools for your deployment — same convention.

### Adapter Tools (config-driven, from module.json)

Registered dynamically from `module.json` tool declarations:
- Each module declares tools with type + field schemas
- Config resolved via 3-level fallback (ENV → DB → config.json)
- Tools missing required config (host, pass) are skipped with a warning

## Tool Registration Flow

1. `config-loader.js` scans `modules/core/*/` and `modules/user/*/`
2. **Adapter tools:** resolves config fields, groups by type, passes to adapter register functions
3. **Module tools:** discovers `toolbox/*.js` files, dynamically imports, calls `register(server, context)`
4. Context provides: `{ app, log, db, playwright }` — no global imports needed in module JS

Source: [src/agento/toolbox/config-loader.js](../../src/agento/toolbox/config-loader.js)

## Further Reading

- [Adding a Tool](adding-a-tool.md) — end-to-end tutorial (MySQL example)
- [Built-in Adapters](built-in-adapters.md) — mysql, mssql, opensearch
- [Creating an Adapter](creating-an-adapter.md) — add a new adapter type
