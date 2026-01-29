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
