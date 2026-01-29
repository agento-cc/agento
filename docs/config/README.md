# Configuration System

Magento-inspired 3-level config resolution with encrypted secrets.

## Fallback Hierarchy

```
┌─────────────────────────────────────────┐
│  1. ENV var (highest priority)          │  CONFIG__MODULE__TOOLS__TOOL__FIELD
├─────────────────────────────────────────┤
│  2. DB: core_config_data (scoped)      │  bin/agento config:set path value [--scope=S --scope-id=N]
│     agent_view → workspace → default   │
├─────────────────────────────────────────┤
│  3. config.json (lowest priority)      │  modules/{name}/config.json
└─────────────────────────────────────────┘
```

Most specific wins. Each level overrides the ones below it.

DB values support Magento-style scoping: `--scope=agent_view --scope-id=1` overrides `--scope=workspace --scope-id=2` overrides `default/0`.

## When to Use Each Level

| Level | Use Case | Example |
|-------|----------|---------|
| **ENV** | Docker/K8s deployments, CI overrides | `CONFIG__JIRA__HOST=https://staging.atlassian.net` |
| **DB** | Secrets, per-installation overrides | `bin/agento config:set jira/token my-api-token` |
| **config.json** | Shared defaults across deployments | `{"tools": {"mysql_prod": {"port": 3306}}}` |

## How It Works at Runtime

Toolbox reads config at each MCP session:

1. Scans `/modules/*/module.json` for tool definitions
2. Loads all `core_config_data` rows from DB (one query, cached per session)
3. For each tool field: checks ENV → DB → config.json
4. Passes resolved config to tool adapter

Source: [docker/toolbox/config-loader.js](../../docker/toolbox/config-loader.js)

## Further Reading

- [ENV Variables](env-vars.md) — naming convention and examples
- [core_config_data](core-config-data.md) — DB table and CLI
- [Encryption](encryption.md) — obscure fields and AES-256-CBC
