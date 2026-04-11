import { z } from 'zod';
import mysql from 'mysql2/promise';
import { logToolbox as log } from '../log.js';
import { getSqlTimeoutMs, setSqlTimeoutSeconds } from './sql-timeout.js';
import { maybeOffloadRows } from './large-result.js';

const ALLOWED_KEYWORDS = ['SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN', 'WITH'];

function isReadOnly(query) {
  const normalized = query.trim().replace(/\/\*[\s\S]*?\*\//g, '').trim();
  const firstWord = normalized.split(/\s/)[0].toUpperCase();
  return ALLOWED_KEYWORDS.includes(firstWord);
}

function createMysqlTool(server, toolName, description, config, offload) {
  let pool = null;

  function getPool() {
    if (!pool) {
      pool = mysql.createPool({
        host: config.host,
        port: parseInt(config.port || '3306'),
        user: config.user,
        password: config.pass,
        database: config.database,
        waitForConnections: true,
        connectionLimit: 2,
      });
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
          content: [{ type: 'text', text: 'Error: Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are allowed.' }],
          isError: true,
        };
      }

      log(toolName, 'QUERY', `user=${user} | ${query}`);
      const start = Date.now();

      try {
        const [rows] = await getPool().query({ sql: query, timeout: getSqlTimeoutMs() });
        const elapsed = Date.now() - start;
        const rowCount = Array.isArray(rows) ? rows.length : '?';

        const offloaded = Array.isArray(rows) && rows.length > 0
          ? await maybeOffloadRows(rows, toolName, offload)
          : null;

        const offloadInfo = offloaded ? `offload=${offloaded.filePath}` : 'offload=none';
        log(toolName, 'OK', `user=${user} time=${elapsed}ms rows=${rowCount} ${offloadInfo}`);

        const text = offloaded ? offloaded.summary : JSON.stringify(rows, null, 2);
        return { content: [{ type: 'text', text }] };
      } catch (err) {
        log(toolName, 'ERROR', `user=${user} ${err.message}`);
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
 * Register MySQL tools from pre-resolved tool configs.
 * @param {object} server - MCP server
 * @param {Array<{name, description, config}>} tools - Resolved tool configs from config-loader
 * @returns {{ names: string[], healthcheck: () => Promise<Array> }} Registered tool names and healthcheck function
 */
export function registerMysqlTools(server, tools, options = {}) {
  if (options.sqlTimeoutSeconds !== null && options.sqlTimeoutSeconds !== undefined) {
    setSqlTimeoutSeconds(options.sqlTimeoutSeconds);
  }
  const registered = [];
  const poolRefs = [];

  for (const tool of tools) {
    const getPool = createMysqlTool(server, tool.name, tool.description, tool.config, options.offload || {});
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
