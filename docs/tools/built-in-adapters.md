# Built-in Tool Adapters

Three database adapters ship with Agento. Each reads config from the module's field schema.

## MySQL

Read-only SQL queries against MySQL/MariaDB databases.

**Required fields:** `host`, `pass`
**Optional fields:** `port` (default: 3306), `user`, `database`

**Enforced:** Only `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH` queries allowed.

**Timeout:** Controlled by `SQL_TIMEOUT_SECONDS` env var (default: 300s).

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
        "database": {"type": "string", "label": "Database"}
      }
    }
  ]
}
```

## SQL Timeout

Set globally via env var in docker-compose:

```yaml
toolbox:
  environment:
    SQL_TIMEOUT_SECONDS: 300   # 5 minutes (default)
```

Source: [src/agento/toolbox/adapters/sql-timeout.js](../../src/agento/toolbox/adapters/sql-timeout.js)

## Large Result Offload

When a query result exceeds a configurable size threshold, the full result is saved as a CSV file to disk and a summary with sample rows is returned to the agent instead. This prevents oversized responses from consuming agent context window.

**Config paths** (core module, 3-level fallback):

| Path | Default | Description |
|------|---------|-------------|
| `core/toolbox/result_offload/threshold` | 20000 | Size threshold in bytes (estimated via JSON.stringify) |
| `core/toolbox/result_offload/sample_rows` | 5 | Number of sample rows included in the summary |
| `core/toolbox/result_offload/text_preview_chars` | 200 | Number of preview characters for text offload |

Files are written to `${artifactsDir}/mcp-results/{toolName}/result_{timestamp}.csv` (where `artifactsDir` is `/workspace/artifacts/{workspace}/{agent_view}/{job_id}`). Cleanup of old offload files is the responsibility of the artifacts dir lifecycle manager, not this middleware.

Override per agent_view:
```bash
agento config:set core/toolbox/result_offload/threshold 50000 --scope=agent_view --scope-id=1
```

Source: [src/agento/toolbox/adapters/large-result.js](../../src/agento/toolbox/adapters/large-result.js)
