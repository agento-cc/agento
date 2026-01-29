import { z } from 'zod';
import { logToolbox as log } from '../log.js';

function createOpensearchTool(server, toolName, description, config) {
  server.tool(
    toolName,
    description,
    {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      index: z.string().describe('Index pattern, e.g. "my-index-*"'),
      query: z.string().optional().describe('JSON query body for _search. Omit to get index info.'),
    },
    async ({ user: agentUser, index, query }) => {
      if (!config.host || !config.pass) {
        log(toolName, 'ERROR', `user=${agentUser} - not configured (missing host or pass)`);
        return {
          content: [{ type: 'text', text: `Error: ${toolName} not configured. Set host and pass via bin/agento config:set or ENV vars.` }],
          isError: true,
        };
      }

      const auth = Buffer.from(`${config.user}:${config.pass}`).toString('base64');
      const headers = {
        'Authorization': `Basic ${auth}`,
        'Content-Type': 'application/json',
      };

      try {
        let url, options;
        if (query) {
          url = `${config.host}/${index}/_search`;
          options = { method: 'POST', headers, body: query };
        } else {
          url = `${config.host}/${index}`;
          options = { method: 'GET', headers };
        }

        const response = await fetch(url, options);
        const data = await response.json();
        log(toolName, 'OK', `user=${agentUser} index=${index} search=${!!query}`);
        return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
      } catch (err) {
        log(toolName, 'ERROR', `user=${agentUser} ${err.message}`);
        return {
          content: [{ type: 'text', text: `OpenSearch error: ${err.message}` }],
          isError: true,
        };
      }
    }
  );
}

/**
 * Register OpenSearch tools from pre-resolved tool configs.
 * @returns {{ names: string[], healthcheck: () => Promise<Array> }}
 */
export function registerOpensearchTools(server, tools, _options = {}) {
  const registered = [];
  const configRefs = [];

  for (const tool of tools) {
    createOpensearchTool(server, tool.name, tool.description, tool.config);
    registered.push(tool.name);
    configRefs.push({ name: tool.name, config: tool.config });
  }

  async function healthcheck() {
    const results = [];
    for (const { name, config } of configRefs) {
      if (!config.host || !config.pass) {
        results.push({ tool: name, status: 'skip', error: 'not configured' });
        continue;
      }
      const start = Date.now();
      try {
        const auth = Buffer.from(`${config.user}:${config.pass}`).toString('base64');
        const response = await fetch(config.host, {
          method: 'GET',
          headers: { 'Authorization': `Basic ${auth}` },
        });
        if (response.ok) {
          results.push({ tool: name, status: 'ok', ms: Date.now() - start });
        } else {
          results.push({ tool: name, status: 'fail', ms: Date.now() - start, error: `HTTP ${response.status}` });
        }
      } catch (err) {
        results.push({ tool: name, status: 'fail', ms: Date.now() - start, error: err.message });
      }
    }
    return results;
  }

  return { names: registered, healthcheck };
}
