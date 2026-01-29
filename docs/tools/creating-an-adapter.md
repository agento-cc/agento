# Creating a Tool Adapter

Add a new database or service type (e.g., PostgreSQL, Redis, MongoDB).

## 1. Create the Adapter File

Create `src/agento/toolbox/adapters/postgres.js`:

```javascript
import { z } from 'zod';
import pg from 'pg';
import { logToolbox as log } from '../log.js';

function createPostgresTool(server, toolName, description, config) {
  let pool = null;

  function getPool() {
    if (!pool) {
      pool = new pg.Pool({
        host: config.host,
        port: parseInt(config.port || '5432'),
        user: config.user,
        password: config.pass,
        database: config.database,
        max: 2,
      });
    }
    return pool;
  }

  server.tool(
    toolName,
    description,
    {
      user: z.string().email().describe('Agent email from SOUL.md'),
      query: z.string().describe('SQL query (SELECT only)'),
    },
    async ({ user, query }) => {
      // ... validate read-only, execute, return results
      // See mysql.js for the full pattern
    }
  );
}

export function registerPostgresTools(server, tools) {
  const registered = [];
  const poolRefs = [];

  for (const tool of tools) {
    createPostgresTool(server, tool.name, tool.description, tool.config);
    registered.push(tool.name);
    poolRefs.push({ name: tool.name, config: tool.config });
  }

  async function healthcheck() {
    const results = [];
    for (const { name, config } of poolRefs) {
      if (!config.host || !config.pass) {
        results.push({ tool: name, status: 'skip', error: 'not configured' });
        continue;
      }
      const start = Date.now();
      try {
        // Adapter-specific connectivity check
        await getPool().query('SELECT 1');
        results.push({ tool: name, status: 'ok', ms: Date.now() - start });
      } catch (err) {
        results.push({ tool: name, status: 'fail', ms: Date.now() - start, error: err.message });
      }
    }
    return results;
  }

  return { names: registered, healthcheck };
}
```

## 2. Register in ADAPTERS Map

Edit `src/agento/toolbox/adapters/index.js`:

```javascript
import { registerPostgresTools } from './postgres.js';

const ADAPTERS = {
  mysql: registerMysqlTools,
  mssql: registerMssqlTools,
  opensearch: registerOpensearchTools,
  postgres: registerPostgresTools,  // NEW
};
```

That's it. The config-loader already handles any type — it just passes resolved config to the adapter.

## 3. Use in a Module

```json
{
  "tools": [{
    "type": "postgres",
    "name": "pg_analytics",
    "description": "Analytics PostgreSQL database",
    "fields": {
      "host": {"type": "string", "label": "Host"},
      "port": {"type": "integer", "label": "Port", "default": 5432},
      "user": {"type": "string", "label": "User"},
      "pass": {"type": "obscure", "label": "Password"},
      "database": {"type": "string", "label": "Database"}
    }
  }]
}
```

## 4. Install npm Package

```bash
cd src/agento/toolbox && npm install pg
```

## Adapter Contract

Each adapter exports a register function with this signature:

```typescript
function registerXxxTools(
  server: McpServer,
  tools: Array<{ name: string, description: string, config: Record<string, any> }>,
  options?: { sqlTimeoutSeconds?: number }
): { names: string[], healthcheck: () => Promise<Array<{ tool: string, status: 'ok' | 'fail' | 'skip', ms?: number, error?: string }>> }
```

The `config` object contains resolved values from the 3-level fallback. Fields match the `fields` schema in module.json.

The `healthcheck` function is called by `/health?test=true` to verify connectivity. It should return one result per tool: `ok` (connected), `fail` (error), or `skip` (not configured).

## Module JS Tool Healthchecks

Convention-based JS tools (`toolbox/*.js`) can also export a `healthcheck(context)` function alongside `register()`. It receives the same context and returns an array of results:

```javascript
export async function healthcheck({ moduleConfigs, db }) {
  const start = Date.now();
  try {
    await db.getCronPool().query('SELECT 1');
    return [{ tool: 'my_tool', status: 'ok', ms: Date.now() - start }];
  } catch (err) {
    return [{ tool: 'my_tool', status: 'fail', ms: Date.now() - start, error: err.message }];
  }
}
```

For tools that cover a group (e.g. all `jira_*` tools), use a group name like `jira` — the test script maps group names to individual tools by prefix.

## Reference

Use [src/agento/toolbox/adapters/mysql.js](../../src/agento/toolbox/adapters/mysql.js) as a template — it covers read-only enforcement, error handling, logging, connection pooling, and healthcheck.
