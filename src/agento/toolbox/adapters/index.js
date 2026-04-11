import { registerMysqlTools } from './mysql.js';
import { registerMssqlTools } from './mssql.js';
import { registerOpensearchTools } from './opensearch.js';

const ADAPTERS = {
  mysql: registerMysqlTools,
  mssql: registerMssqlTools,
  opensearch: registerOpensearchTools,
};

/**
 * Register config-driven adapter tools (mysql, mssql, opensearch) from module.json declarations.
 * @param {object} moduleConfigs - Resolved module-level configs (for sql_timeout_seconds etc.)
 * @param {object} context - Shared context with artifactsDir
 * @returns {{ names: string[], healthchecks: Array<() => Promise<Array>> }}
 */
export function registerAdapterTools(server, allTools, moduleToolTypes, moduleConfigs = {}, context = {}) {
  const dynamicNames = [];
  const healthchecks = [];
  const sqlTimeoutSeconds = parseInt(moduleConfigs?.core?.sql_timeout_seconds || '300', 10);
  const offload = {
    artifactsDir: context.artifactsDir,
    threshold: parseInt(moduleConfigs?.core?.['toolbox/result_offload/threshold'] || '20000', 10),
    sampleRows: parseInt(moduleConfigs?.core?.['toolbox/result_offload/sample_rows'] || '5', 10),
    textPreviewChars: parseInt(moduleConfigs?.core?.['toolbox/result_offload/text_preview_chars'] || '200', 10),
  };

  for (const [type, registerFn] of Object.entries(ADAPTERS)) {
    const tools = allTools.filter(t => t.type === type);
    const { names, healthcheck } = registerFn(server, tools, { sqlTimeoutSeconds, offload });
    dynamicNames.push(...names);
    healthchecks.push(healthcheck);
  }

  // Warn about unknown tool types
  for (const type of moduleToolTypes) {
    if (!ADAPTERS[type]) {
      console.error(
        `[tools] No adapter for tool type "${type}". Registered adapters: ${Object.keys(ADAPTERS).join(', ')}`
      );
    }
  }

  return { names: dynamicNames, healthchecks };
}
