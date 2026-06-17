import { registerMysqlTools } from './mysql.js';
import { registerMssqlTools } from './mssql.js';
import { registerOpensearchTools } from './opensearch.js';

const ADAPTERS = {
  mysql: registerMysqlTools,
  mssql: registerMssqlTools,
  opensearch: registerOpensearchTools,
};

// Tool types that are NOT config-driven DB adapters but declarative, self-registering JS tools — a
// module's toolbox/*.js calls server.tool() itself (e.g. type "mcp" for the outlook tools). These have
// no adapter here by design, so they must not trigger the "No adapter for tool type" warning.
const DECLARATIVE_TYPES = new Set(['mcp']);

/**
 * Register config-driven adapter tools (mysql, mssql, opensearch) from module.json declarations.
 * @param {object} moduleConfigs - Resolved module-level configs (for sql_timeout_seconds etc.)
 * @returns {{ names: string[], healthchecks: Array<() => Promise<Array>> }}
 */
export function registerAdapterTools(server, allTools, moduleToolTypes, moduleConfigs = {}) {
  const dynamicNames = [];
  const healthchecks = [];
  const sqlTimeoutSeconds = parseInt(moduleConfigs?.core?.sql_timeout_seconds || '300', 10);

  for (const [type, registerFn] of Object.entries(ADAPTERS)) {
    const tools = allTools.filter(t => t.type === type);
    const { names, healthcheck } = registerFn(server, tools, { sqlTimeoutSeconds });
    dynamicNames.push(...names);
    healthchecks.push(healthcheck);
  }

  // Warn about unknown tool types (declarative self-registering types are expected, not unknown)
  for (const type of moduleToolTypes) {
    if (!ADAPTERS[type] && !DECLARATIVE_TYPES.has(type)) {
      console.error(
        `[tools] No adapter for tool type "${type}". Registered adapters: ${Object.keys(ADAPTERS).join(', ')}`
      );
    }
  }

  return { names: dynamicNames, healthchecks };
}
