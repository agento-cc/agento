# Built-in Tool Adapters

Three database adapters ship with Agento. Each reads config from the module's field schema.

## MySQL

Read-only SQL queries against MySQL/MariaDB databases.

**Required fields:** `host`, `pass`
**Optional fields:** `port` (default: 3306), `user`, `database`

**Enforced:** Only `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH` queries allowed.

**Timeout:** Controlled by `core/sql_timeout_seconds` (default: 300s) through the standard config fallback.

Source: [src/agento/toolbox/adapters/mysql.js](../../src/agento/toolbox/adapters/mysql.js)

## MSSQL

Read-only SQL queries against Microsoft SQL Server.

**Required fields:** `host`, `pass`
**Optional fields:** `port` (default: 1433), `user`, `database`

**Enforced:** Only `SELECT`, `WITH` queries allowed.

Source: [src/agento/toolbox/adapters/mssql.js](../../src/agento/toolbox/adapters/mssql.js)

## OpenSearch

Query OpenSearch/Elasticsearch indices.

**Required fields:** `host` (URL including protocol), `pass`
**Optional fields:** `user`

Supports: index info (GET) and `_search` queries (POST with JSON body).

Source: [src/agento/toolbox/adapters/opensearch.js](../../src/agento/toolbox/adapters/opensearch.js)

## module.json Example

```json
{
  "tools": [
    {
      "type": "mysql",
      "name": "mysql_myapp_prod",
      "description": "My App Production MySQL. Tables: users, orders.",
      "fields": {
        "host": {"type": "string", "label": "Host"},
        "port": {"type": "integer", "label": "Port", "default": 3306},
        "user": {"type": "string", "label": "User"},
        "pass": {"type": "obscure", "label": "Password"},
        "database": {"type": "string", "label": "Database"},
        "client_connection_pool_max_per_tool": {"type": "integer", "label": "Maximum client connections"}
      }
    }
  ]
}
```

## SQL Timeout

Set globally through the standard config path (or its ENV equivalent):

```bash
agento config:set core/sql_timeout_seconds 300
# ENV: CONFIG__CORE__SQL_TIMEOUT_SECONDS=300
```

Source: [src/agento/toolbox/adapters/sql-timeout.js](../../src/agento/toolbox/adapters/sql-timeout.js)

## SQL Connection Pools

MySQL and MSSQL pools are scoped to the adapter type, tool name, and fully resolved connection configuration. Identical configurations reuse one lazy pool across MCP sessions; different tools never share one, even when they target the same server.

Each active tool configuration is limited by `core/client_connection_pool_max_per_tool` (default 10). Override one tool with `<module>/tools/<tool>/client_connection_pool_max_per_tool`. A pool that has no active operation for 30 seconds is closed, and all SQL pools are closed when the toolbox receives `SIGTERM`.

All pools targeting the same adapter, host, and port share `core/server_concurrency_budget` (default 10). This is a process-wide limit on active database operations, regardless of tool, database, credentials, or agent_view. It does not multiply by the number of pools. The setting is default-scope only so scoped sessions cannot create conflicting server-wide budgets. At most 100 operations may wait per server endpoint; queued operations are cancelled when their SQL deadline expires (or an AbortSignal is supplied and aborted).

SQL healthchecks use the same server budget but are actively cancelled at the health endpoint deadline: MySQL destroys its borrowed connection and MSSQL cancels its request. A timed-out `/health?test=true` therefore cannot leave an invisible query occupying the shared budget.

```bash
# Defaults applied to every SQL tool and every DB server endpoint
agento config:set core/client_connection_pool_max_per_tool 10
agento config:set core/server_concurrency_budget 10

# Optional override for one tool's client pool
agento config:set acme/tools/mysql_acme_prod/client_connection_pool_max_per_tool 20
```

## Large Result Offload

The framework automatically wraps ALL tool handlers with result offload middleware. When a tool result exceeds a configurable size threshold, the full result is saved to disk and a summary is returned to the agent instead. This prevents oversized responses from consuming agent context window.

The middleware is applied transparently via the `server.tool` wrapper in `config-loader.js` -- individual adapters do not need to implement offload logic.

### Result strategies

Each tool can declare a `resultStrategy` via the optional 5th argument to `server.tool()`:

| Strategy | Behavior |
|----------|----------|
| `'text'` (default) | Offloads to `.txt` when total text content exceeds threshold |
| `'rows'` | Tries to parse each text content item as a JSON array. If found, offloads to `.csv` with column headers and sample rows. Falls back to `.txt` if no valid JSON array. |
| `false` | Explicitly opt out of offload wrapping |

```js
// Your tool gets automatic text offload (default)
server.tool('my_tool', 'description', schema, handler);

// Opt into CSV offload for tabular results
server.tool('my_db_tool', 'description', schema, handler, { resultStrategy: 'rows' });

// Explicitly opt out (e.g., binary/streaming tools)
server.tool('my_special_tool', 'description', schema, handler, { resultStrategy: false });
```

Built-in database adapters (MySQL, MSSQL, OpenSearch) use `resultStrategy: 'rows'`.

### Config paths

Config paths (core module, 3-level fallback):

| Path | Default | Description |
|------|---------|-------------|
| `core/toolbox/result_offload/threshold` | 20000 | Size threshold in bytes (estimated via JSON.stringify) |
| `core/toolbox/result_offload/sample_rows` | 5 | Number of sample rows included in the summary |
| `core/toolbox/result_offload/text_preview_chars` | 200 | Number of preview characters for text offload |

Files are written to `${artifactsDir}/mcp-results/{toolName}/result_{timestamp}.{csv,txt}` (where `artifactsDir` is `/workspace/artifacts/{workspace}/{agent_view}/{job_id}`). Cleanup of old offload files is the responsibility of the artifacts dir lifecycle manager, not this middleware.

Override per agent_view:
```bash
agento config:set core/toolbox/result_offload/threshold 50000 --scope=agent_view --scope-id=1
```

Source: [src/agento/toolbox/adapters/large-result.js](../../src/agento/toolbox/adapters/large-result.js)
