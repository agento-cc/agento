import { randomUUID } from 'node:crypto';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express from 'express';
import { registerTools, loadModuleConfigs, loadScopedDbOverrides } from './config-loader.js';
import { logToolbox, logPublisher, createScopedLogger } from './log.js';
import * as db from './db.js';
import * as playwright from './playwright-client.js';

const PORT = process.env.PORT || 3001;

const app = express();
// NOTE: no express.json() here — SSEServerTransport reads raw body from req stream

const sessions = new Map();

// Shared context passed to all module register() functions
const context = {
  app,
  log: logToolbox,
  logPublisher,
  db,
  playwright: {
    getClient: playwright.getPlaywrightClient,
    getTools: playwright.getPlaywrightTools,
  },
};

let registeredToolNames = [];
let registeredHealthchecks = [];

async function createServer(agentViewId = null) {
  const server = new McpServer({
    name: 'toolbox',
    version: '1.0.0',
  });

  // Build scoped context with agent_view-aware logger before registering tools,
  // so adapters use the scoped log from the start.
  let sessionContext = context;
  let preloadedOverrides = null;
  if (agentViewId) {
    const { overrides, agentViewMeta } = await loadScopedDbOverrides(agentViewId);
    preloadedOverrides = overrides;
    if (agentViewMeta) {
      const scopedLog = createScopedLogger(agentViewMeta);
      sessionContext = { ...context, log: scopedLog };
    }
  }

  const { toolNames, healthchecks } = await registerTools(server, sessionContext, agentViewId, preloadedOverrides);
  registeredToolNames = toolNames;
  registeredHealthchecks = healthchecks;
  return { server, healthchecks };
}

app.get('/sse', async (req, res) => {
  const agentViewId = req.query.agent_view_id ? parseInt(req.query.agent_view_id, 10) : null;
  const transport = new SSEServerTransport('/messages', res);
  sessions.set(transport.sessionId, transport);

  const { server } = await createServer(agentViewId);

  res.on('close', () => {
    sessions.delete(transport.sessionId);
    server.close().catch(() => {});
  });

  await server.connect(transport);
});

app.post('/messages', async (req, res) => {
  const sessionId = req.query.sessionId;
  const transport = sessions.get(sessionId);
  if (transport) {
    await transport.handlePostMessage(req, res);
  } else {
    res.status(400).json({ error: 'Unknown session' });
  }
});

// Streamable HTTP transport (used by Codex and newer MCP clients)
// Stateful: reuse server+transport per session to avoid re-registering tools on every request
const mcpSessions = new Map();

app.all('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'];
  if (sessionId && mcpSessions.has(sessionId)) {
    const { transport } = mcpSessions.get(sessionId);
    await transport.handleRequest(req, res, req.body);
    return;
  }

  const agentViewId = req.query.agent_view_id ? parseInt(req.query.agent_view_id, 10) : null;
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),
  });
  const { server } = await createServer(agentViewId);

  transport.onclose = () => {
    if (transport.sessionId) {
      mcpSessions.delete(transport.sessionId);
    }
    server.close().catch(() => {});
  };

  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);

  if (transport.sessionId) {
    mcpSessions.set(transport.sessionId, { transport, server });
  }
});

// REST API for internal services (publisher)
// Jira credentials resolved via 3-level config fallback (ENV > DB > config.json)
let jiraConfig = null;

async function getJiraConfig() {
  if (!jiraConfig) {
    const moduleConfigs = await loadModuleConfigs();
    jiraConfig = moduleConfigs.jira || {};
  }
  return jiraConfig;
}

app.post('/api/jira/search', express.json(), async (req, res) => {
  const { jql, fields = [], maxResults = 50 } = req.body;

  if (!jql) {
    return res.status(400).json({ error: 'jql is required' });
  }

  const cfg = await getJiraConfig();
  const user = cfg.jira_user;
  const token = cfg.jira_token;
  const host = cfg.jira_host;

  if (!user || !token) {
    return res.status(500).json({ error: 'jira/jira_user or jira/jira_token not configured' });
  }

  const auth = Buffer.from(`${user}:${token}`).toString('base64');

  try {
    const response = await fetch(`${host}/rest/api/3/search/jql`, {
      method: 'POST',
      headers: {
        'Authorization': `Basic ${auth}`,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ jql, fields, maxResults }),
    });

    if (!response.ok) {
      const text = await response.text();
      logPublisher('api/jira/search', 'ERROR', `HTTP ${response.status}: ${text}`);
      return res.status(response.status).json({ error: text });
    }

    const data = await response.json();
    const count = (data.issues || []).length;
    logPublisher('api/jira/search', 'OK', `jql="${jql}" -> ${count} results`);
    res.json(data);
  } catch (err) {
    logPublisher('api/jira/search', 'ERROR', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/jira/issue/comments', express.json(), async (req, res) => {
  const { issue_key } = req.body;

  if (!issue_key) {
    return res.status(400).json({ error: 'issue_key is required' });
  }

  const cfg = await getJiraConfig();
  const user = cfg.jira_user;
  const token = cfg.jira_token;
  const host = cfg.jira_host;

  if (!user || !token) {
    return res.status(500).json({ error: 'jira/jira_user or jira/jira_token not configured' });
  }

  const auth = Buffer.from(`${user}:${token}`).toString('base64');

  try {
    const response = await fetch(
      `${host}/rest/api/2/issue/${encodeURIComponent(issue_key)}/comment?maxResults=100`,
      {
        headers: {
          'Authorization': `Basic ${auth}`,
          'Accept': 'application/json',
        },
      },
    );

    if (!response.ok) {
      const text = await response.text();
      logPublisher('api/jira/issue/comments', 'ERROR', `HTTP ${response.status}: ${text}`);
      return res.status(response.status).json({ error: text });
    }

    const data = await response.json();
    const comments = (data.comments || []).map((c) => ({
      id: c.id,
      author: {
        displayName: c.author?.displayName,
        emailAddress: c.author?.emailAddress,
        accountId: c.author?.accountId,
      },
      body: c.body,
      created: c.created,
    }));
    logPublisher('api/jira/issue/comments', 'OK', `issue=${issue_key} -> ${comments.length} comments`);
    res.json({ comments });
  } catch (err) {
    logPublisher('api/jira/issue/comments', 'ERROR', err.message);
    res.status(500).json({ error: err.message });
  }
});

const HEALTHCHECK_TIMEOUT_MS = 10_000;

async function runHealthchecks(healthchecks) {
  const results = await Promise.allSettled(
    healthchecks.map(fn =>
      Promise.race([
        fn(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), HEALTHCHECK_TIMEOUT_MS)),
      ])
    )
  );

  const checks = [];
  for (const result of results) {
    if (result.status === 'fulfilled') {
      checks.push(...result.value);
    } else {
      checks.push({ tool: 'unknown', status: 'fail', error: result.reason?.message || 'unknown error' });
    }
  }
  return checks;
}

app.get('/health', async (req, res) => {
  const agentViewId = req.query.agent_view_id ? parseInt(req.query.agent_view_id, 10) : null;
  const runTests = req.query.test === 'true';

  let tools;
  let healthchecks;

  if (agentViewId) {
    const tmpServer = new McpServer({ name: 'toolbox-health', version: '1.0.0' });
    const { overrides, agentViewMeta } = await loadScopedDbOverrides(agentViewId);
    const sessionContext = agentViewMeta
      ? { ...context, log: createScopedLogger(agentViewMeta) }
      : context;
    const result = await registerTools(tmpServer, sessionContext, agentViewId, overrides);
    tools = result.toolNames;
    healthchecks = result.healthchecks;
  } else {
    tools = registeredToolNames;
    healthchecks = registeredHealthchecks;
  }

  if (!runTests) {
    const response = { status: 'ok', tools };
    if (agentViewId) response.agent_view_id = agentViewId;
    return res.json(response);
  }

  const checks = await runHealthchecks(healthchecks);
  const hasFail = checks.some(c => c.status === 'fail');
  const response = {
    status: hasFail ? 'degraded' : 'ok',
    tools,
    checks,
  };
  if (agentViewId) response.agent_view_id = agentViewId;
  res.json(response);
});

// Start Playwright MCP child process, then listen
playwright.initPlaywright()
  .then(() => {
    app.listen(PORT, '0.0.0.0', () => {
      console.log(`Toolbox MCP server listening on port ${PORT}`);
    });
  })
  .catch((err) => {
    logToolbox('playwright', 'ERROR', `Failed to start Playwright MCP: ${err.message}. Browser tools will be unavailable.`);
    // Start server anyway — non-browser tools should still work
    app.listen(PORT, '0.0.0.0', () => {
      console.log(`Toolbox MCP server listening on port ${PORT} (without Playwright)`);
    });
  });

// Graceful shutdown
process.on('SIGTERM', async () => {
  await playwright.closePlaywright();
  process.exit(0);
});
