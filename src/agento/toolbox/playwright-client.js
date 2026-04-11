import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { readFile, writeFile } from 'fs/promises';
import { logToolbox as log } from './log.js';

let client = null;
let transport = null;
let discoveredTools = [];

async function buildMcpArgs() {
  const args = ['@playwright/mcp', '--headless', '--browser', 'chromium', '--ignore-https-errors', '--caps', 'devtools'];

  let session = {};
  try {
    const raw = await readFile('/app/session.json', 'utf8');
    session = JSON.parse(raw);
    log('playwright', 'SESSION', 'Loaded session.json');
  } catch {
    // No session.json — proceed with defaults
  }

  if (session.viewport) {
    args.push('--viewport-size', `${session.viewport.width},${session.viewport.height}`);
  }
  if (session.userAgent) {
    args.push('--user-agent', session.userAgent);
  }
  if (session.cookies?.length) {
    const storageState = { cookies: session.cookies, origins: [] };
    await writeFile('/tmp/pw-storage.json', JSON.stringify(storageState));
    args.push('--storage-state', '/tmp/pw-storage.json');
  }

  return args;
}

export async function initPlaywright() {
  transport = new StdioClientTransport({
    command: 'npx',
    args: await buildMcpArgs(),
    stderr: 'pipe',
  });

  // Log Playwright MCP's stderr
  transport.stderr?.on('data', (chunk) => {
    const msg = chunk.toString().trim();
    if (msg) log('playwright-mcp', 'STDERR', msg);
  });

  client = new Client(
    { name: 'toolbox-playwright', version: '1.0.0' },
    { capabilities: {} },
  );

  await client.connect(transport);
  log('playwright', 'INIT', 'Playwright MCP child process started');

  // Discover available tools and log them
  try {
    const { tools } = await client.listTools();
    discoveredTools = tools;
    const names = tools.map(t => t.name);
    log('playwright', 'TOOLS', `${names.length} available: ${names.join(', ')}`);
  } catch (err) {
    log('playwright', 'WARN', `Failed to list tools: ${err.message}`);
  }

  client.onclose = () => {
    log('playwright', 'CLOSE', 'Playwright MCP child process closed');
    client = null;
  };

  return client;
}

export function getPlaywrightClient() {
  return client;
}

export function getPlaywrightTools() {
  return discoveredTools;
}

export async function closePlaywright() {
  if (client) {
    await client.close().catch(() => {});
    client = null;
  }
}
