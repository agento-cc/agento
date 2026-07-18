import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerTools, loadScopedDbOverrides } from './config-loader.js';
import { createScopedLogger } from './log.js';

export async function createHealthRegistration(agentViewId, context) {
  const server = new McpServer({ name: 'toolbox-health', version: '1.0.0' });
  let overrides = null;
  let sessionContext = context;

  if (agentViewId) {
    const scoped = await loadScopedDbOverrides(agentViewId);
    overrides = scoped.overrides;
    if (scoped.agentViewMeta) {
      sessionContext = { ...context, log: createScopedLogger(scoped.agentViewMeta) };
    }
  }

  const result = await registerTools(server, sessionContext, agentViewId, overrides);
  return { tools: result.toolNames, healthchecks: result.healthchecks };
}
