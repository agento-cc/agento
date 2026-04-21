# Zero-Trust Credential Model

Toolbox is the **only** container with access to secrets. The AI agent has no credentials.

## Security Boundary

```
┌────────────────────────────────────┐
│  Agent (cron/sandbox)              │
│                                    │
│  Has: workspace, tokens (OAuth),   │
│       SSH key, modules (read-only) │
│                                    │
│  Does NOT have: secrets.env,       │
│  database passwords, API tokens    │
│  (except its own OAuth)            │
└───────────┬────────────────────────┘
            │ MCP over SSE (Claude) or streamable HTTP (Codex) — no credentials in request
            ▼
┌────────────────────────────────────┐
│  Toolbox                           │
│                                    │
│  Has: secrets.env, JIRA_TOKEN,     │
│       all DB passwords, SMTP,      │
│       AGENTO_ENCRYPTION_KEY        │
│                                    │
│  Validates: read-only queries,     │
│  email whitelist, domain whitelist  │
└────────────────────────────────────┘
```

## How It Works

1. Agent calls MCP tool: `mysql_myapp_prod` with query `SELECT * FROM users LIMIT 5`
2. Toolbox receives the request (no credentials in the request — just tool name + query)
3. Toolbox resolves connection config from modules + core_config_data + ENV
4. Toolbox validates the query is read-only (`SELECT` only)
5. Toolbox executes the query using its own credentials
6. Toolbox returns results to the agent

## Why Two Languages

The Python/Node.js split is **intentional** — the language boundary IS the security boundary:

- **Python (cron):** Runs the LLM, executes Claude/Codex CLI, manages job queue. Has OAuth tokens for AI providers but no database/API credentials.
- **Node.js (toolbox):** Holds all credentials, executes database queries, manages Jira API. Never runs LLM code.

You cannot accidentally `import secrets` in agent code because it's a different language, different container, different filesystem.

## Credential Flow

```
secrets.env (host filesystem)
    │
    └──► toolbox container (env_file in docker-compose)
              │
              ├── JIRA_HOST, JIRA_USER, JIRA_TOKEN
              ├── SMTP_HOST, SMTP_USER, SMTP_PASS
              ├── AGENTO_ENCRYPTION_KEY
              └── CONFIG__* overrides

              + core_config_data (MySQL) for per-tool credentials
```

## What the Agent CAN Access

- Its own OAuth tokens (Claude/Codex) — stored in `tokens/`, mounted to `/etc/tokens`
- SSH key — for cloning git repositories
- MCP tools — through toolbox, which validates and executes requests
- Filesystem — workspace/, modules/ (read-only)
