import { z } from 'zod';
import sql from 'mssql';
import { logToolbox as log } from '../log.js';
import { getSqlTimeoutMs } from './sql-timeout.js';
import { maybeOffloadRows } from './large-result.js';

const ALLOWED_KEYWORDS = ['SELECT', 'WITH', 'SHOW', 'EXEC SP_HELP'];

function isReadOnly(query) {
  const normalized = query.trim().replace(/\/\*[\s\S]*?\*\//g, '').trim();
  const firstWord = normalized.split(/\s/)[0].toUpperCase();
  return ALLOWED_KEYWORDS.includes(firstWord);
}

function createMssqlTool(server, toolName, description, config, offload) {
  const mssqlConfig = {
    server: config.host,
    port: parseInt(config.port || '1433'),
    user: config.user,
    password: config.pass,
    database: config.database,
    options: { trustServerCertificate: true },
    pool: { max: 2, min: 0, idleTimeoutMillis: 30000 },
  };

  let pool = null;

  async function getPool() {
    if (!pool) {
      pool = await sql.connect(mssqlConfig);
    }
    return pool;
  }

  server.tool(
    toolName,
    description,
    {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      query: z.string().describe('SQL query to execute (SELECT only)'),
    },
    async ({ user, query }) => {
      if (!config.host || !config.pass) {
        log(toolName, 'ERROR', `user=${user} - not configured (missing host or pass)`);
        return {
          content: [{ type: 'text', text: `Error: ${toolName} not configured. Set host and pass via bin/agento config:set or ENV vars.` }],
          isError: true,
        };
      }

      if (!isReadOnly(query)) {
        log(toolName, 'BLOCKED', `user=${user} non-readonly query: ${query.substring(0, 80)}`);
        return {
          content: [{ type: 'text', text: 'Error: Only SELECT and WITH queries are allowed.' }],
          isError: true,
        };
      }

      log(toolName, 'QUERY', `user=${user} | ${query}`);
      const start = Date.now();

      try {
        const p = await getPool();
        const req = p.request();
        req.timeout = getSqlTimeoutMs();
        const result = await req.query(query);
        const elapsed = Date.now() - start;
        const rows = result.recordset;

        const offloaded = rows.length > 0
          ? await maybeOffloadRows(rows, toolName, offload)
          : null;

        const offloadInfo = offloaded ? `offload=${offloaded.filePath}` : 'offload=none';
        log(toolName, 'OK', `user=${user} time=${elapsed}ms rows=${rows.length} ${offloadInfo}`);

        const text = offloaded ? offloaded.summary : JSON.stringify(rows, null, 2);
        return { content: [{ type: 'text', text }] };
      } catch (err) {
        log(toolName, 'ERROR', `user=${user} ${err.message}`);
        if (err.code === 'ECONNREFUSED' || err.code === 'ETIMEOUT') {
          pool = null;
        }
        return {
          content: [{ type: 'text', text: `Query error: ${err.message}` }],
          isError: true,
        };
      }
    }
  );

  return getPool;
}

/**
 * Register MSSQL tools from pre-resolved tool configs.
 * @returns {{ names: string[], healthcheck: () => Promise<Array> }}
 */
export function registerMssqlTools(server, tools, options = {}) {
  const registered = [];
  const poolRefs = [];

  for (const tool of tools) {
    const getPool = createMssqlTool(server, tool.name, tool.description, tool.config, options.offload || {});
    registered.push(tool.name);
    poolRefs.push({ name: tool.name, getPool, config: tool.config });
  }

  async function healthcheck() {
    const results = [];
    for (const { name, getPool, config } of poolRefs) {
      if (!config.host || !config.pass) {
        results.push({ tool: name, status: 'skip', error: 'not configured' });
        continue;
      }
      const start = Date.now();
      try {
        const p = await getPool();
        await p.request().query('SELECT 1');
        results.push({ tool: name, status: 'ok', ms: Date.now() - start });
      } catch (err) {
        results.push({ tool: name, status: 'fail', ms: Date.now() - start, error: err.message });
      }
    }
    return results;
  }

  return { names: registered, healthcheck };
}
