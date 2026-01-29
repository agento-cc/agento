import { z } from 'zod';
import { readFile, writeFile, mkdir } from 'fs/promises';

// --- Session cookie injection ---
let sessionCookies = [];
try {
  const raw = await readFile('/app/session.json', 'utf8');
  sessionCookies = JSON.parse(raw).cookies || [];
} catch {
  // No session.json or no cookies — that's fine
}

const injectedDomains = new Set();

function sessionCookiesForUrl(urlString) {
  let hostname;
  try { hostname = new URL(urlString).hostname.toLowerCase(); } catch { return []; }
  return sessionCookies.filter(c => {
    const domain = (c.domain || '').replace(/^\./, '').toLowerCase();
    return hostname === domain || hostname.endsWith('.' + domain);
  });
}

function buildCookieJs(cookies) {
  return cookies.map(c => {
    let str = `${c.name}=${encodeURIComponent(c.value)}; path=${c.path || '/'}`;
    if (c.domain) str += `; domain=${c.domain}`;
    str += `; max-age=31536000; SameSite=${c.sameSite || 'Lax'}`;
    return `document.cookie=${JSON.stringify(str)}`;
  }).join('; ');
}

// --- Helpers (pure functions, no config dependency) ---

function parseList(value) {
  if (!value) return [];
  return value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

function parseBool(value, defaultValue) {
  if (value === undefined || value === null || value === '') return defaultValue;
  return value === true || value === 'true' || value === '1';
}

// --- JSON Schema → Zod converter (for upstream Playwright tool passthrough) ---

function jsonSchemaPropertyToZod(prop) {
  if (prop.enum) return z.enum(prop.enum);
  switch (prop.type) {
    case 'string':  return z.string();
    case 'number':  return z.number();
    case 'integer': return z.number().int();
    case 'boolean': return z.boolean();
    case 'array':   return z.array(prop.items ? jsonSchemaPropertyToZod(prop.items) : z.unknown());
    case 'object':  return prop.properties
      ? z.object(Object.fromEntries(Object.entries(prop.properties).map(([k, v]) => [k, jsonSchemaPropertyToZod(v)])))
      : z.record(z.unknown());
    default: throw new Error(`Unsupported JSON Schema type: ${prop.type}`);
  }
}

function jsonSchemaToZodShape(inputSchema) {
  const shape = {
    user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
  };
  const props = inputSchema?.properties || {};
  const required = new Set(inputSchema?.required || []);
  for (const [key, prop] of Object.entries(props)) {
    let zodType = jsonSchemaPropertyToZod(prop);
    if (prop.description) zodType = zodType.describe(prop.description);
    if (!required.has(key)) zodType = zodType.optional();
    shape[key] = zodType;
  }
  return shape;
}

// --- Tool definitions (static schemas for known Playwright MCP tools) ---

const BROWSER_TOOLS = {
  browser_navigate: {
    description: [
      'Navigate to a URL in the browser.',
      'Only whitelisted domains and HTTPS (by default) are allowed.',
      'Session cookies from session.json are automatically injected on first visit to a domain.',
      'Returns an accessibility snapshot of the page.',
    ].join('\n'),
    schema: {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      url: z.string().url().describe('URL to navigate to'),
    },
    urlParam: 'url',
    playwrightName: 'browser_navigate',
  },
  browser_wait_for: {
    description: 'Wait for a specified amount of time.',
    schema: {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      time: z.number().int().positive().describe('Time to wait in milliseconds'),
    },
    urlParam: null,
  },
  browser_take_screenshot: {
    description: [
      'Take a screenshot of the current page.',
      'Returns a PNG image. Navigate to a page first.',
      'The screenshot is also saved to /workspace/tmp/screenshots/{job_id}-{reference_id}/{filename}.',
      'Pass job_id and reference_id from your execution context (SOUL.md) to organise the file correctly.',
    ].join('\n'),
    schema: {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      job_id: z.string().optional().describe('Job ID from SOUL.md — used to organise the screenshot folder'),
      reference_id: z.string().optional().describe('Jira issue key from SOUL.md (e.g. "K3-42") — used to organise the screenshot folder'),
      filename: z.string().optional().describe('PNG filename. Defaults to {timestamp}.png. Use a fixed name to overwrite on each run.'),
    },
    urlParam: null,
  },
  browser_snapshot: {
    description: [
      'Capture an accessibility snapshot of the current page.',
      'Returns the page structure as text. Navigate to a page first.',
    ].join('\n'),
    schema: {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
    },
    urlParam: null,
  },
  browser_evaluate: {
    description: [
      'Evaluate a JavaScript arrow function in the current page and return the result.',
      'The function parameter must be an arrow function, e.g. "() => document.title".',
    ].join('\n'),
    schema: {
      user: z.string().email().describe('Your (the LLM agent) email address from SOUL.md — identity credential'),
      function: z.string().describe('Arrow function to evaluate, e.g. "() => document.title"'),
    },
    urlParam: null,
  },
};

const registeredPassthroughNames = [];

// --- Registration ---

export async function healthcheck({ playwright }) {
  const client = playwright.getClient();
  if (!client) {
    return [{ tool: 'browser', status: 'fail', error: 'Playwright MCP not connected' }];
  }
  return [{ tool: 'browser', status: 'ok', ms: 0 }];
}

export function getRegisteredBrowserToolNames() {
  // NOTE: requires register() to have been called first for _toolWhitelist to be set
  return [
    ...Object.keys(BROWSER_TOOLS).filter(name => _toolWhitelist.includes(name)),
    ...registeredPassthroughNames,
  ];
}

let _toolWhitelist = [];

export function register(server, { log, playwright, moduleConfigs, isToolEnabled }) {
  if (isToolEnabled && !isToolEnabled('browser')) return;
  const cfg = moduleConfigs?.core || {};
  const toolWhitelist = [...new Set(parseList(cfg.playwright_tool_whitelist))];
  const allowedDomains = parseList(cfg.allowed_domains);
  const allowSubdomains = parseBool(cfg.allow_subdomains, true);
  const allowHttp = parseBool(cfg.allow_http, false);
  _toolWhitelist = toolWhitelist;

  function validateDomain(urlString) {
    let parsed;
    try {
      parsed = new URL(urlString);
    } catch {
      return { allowed: false, reason: `Invalid URL: "${urlString}"` };
    }

    if (!allowHttp && parsed.protocol === 'http:') {
      return { allowed: false, reason: `HTTP not allowed. Use HTTPS.` };
    }

    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return { allowed: false, reason: `Protocol "${parsed.protocol}" not allowed.` };
    }

    if (allowedDomains.length === 0) {
      return { allowed: false, reason: 'No domains configured (CONFIG__CORE__ALLOWED_DOMAINS).' };
    }

    const hostname = parsed.hostname.toLowerCase();
    const match = allowedDomains.some(domain => {
      if (hostname === domain) return true;
      if (allowSubdomains && hostname.endsWith('.' + domain)) return true;
      return false;
    });

    if (!match) {
      return { allowed: false, reason: `Domain "${hostname}" not in allowed list.` };
    }

    return { allowed: true };
  }

  if (sessionCookies.length) {
    log('browser', 'SESSION', `Loaded ${sessionCookies.length} session cookies for injection`);
  }

  if (toolWhitelist.length === 0) {
    log('browser', 'INIT', 'No tools in PLAYWRIGHT_TOOL_WHITELIST — all browser tools disabled');
    return;
  }

  log('browser', 'INIT', `whitelist=[${toolWhitelist.join(',')}] domains=[${allowedDomains.join(',')}] subdomains=${allowSubdomains} http=${allowHttp}`);

  for (const [name, def] of Object.entries(BROWSER_TOOLS)) {
    if (!toolWhitelist.includes(name)) continue;

    server.tool(
      name,
      def.description,
      def.schema,
      async (args) => {
        // Strip job_id / reference_id / filename — they're ours, not Playwright MCP's
        const { user, job_id, reference_id, filename, ...toolArgs } = args;

        // Domain validation for URL-bearing tools
        if (def.urlParam && args[def.urlParam]) {
          const result = validateDomain(args[def.urlParam]);
          if (!result.allowed) {
            log(name, 'BLOCKED', `user=${user} url="${args[def.urlParam]}" — ${result.reason}`);
            return {
              content: [{ type: 'text', text: `Error: ${result.reason} Allowed domains: ${allowedDomains.join(', ')}` }],
              isError: true,
            };
          }
        }

        const client = playwright.getClient();
        if (!client) {
          log(name, 'ERROR', `user=${user} — Playwright MCP not connected`);
          return {
            content: [{ type: 'text', text: 'Error: Playwright MCP is not available. Browser service may be starting up.' }],
            isError: true,
          };
        }

        try {
          // Pre-navigation cookie injection
          if (name === 'browser_navigate' && toolArgs.url) {
            const preCookies = sessionCookiesForUrl(toolArgs.url);
            let preHostname;
            try { preHostname = new URL(toolArgs.url).hostname; } catch { /* invalid url handled below */ }
            if (preCookies.length && preHostname && !injectedDomains.has(preHostname)) {
              injectedDomains.add(preHostname);
              const parsed = new URL(toolArgs.url);
              const lightUrl = `${parsed.protocol}//${parsed.host}/robots.txt`;
              log(name, 'PRE-NAV', `user=${user} navigating to ${lightUrl} for cookie setup`);
              await client.callTool({ name: 'browser_navigate', arguments: { url: lightUrl } });
              const cookieJs = buildCookieJs(preCookies);
              await client.callTool({ name: 'browser_evaluate', arguments: { function: `() => { ${cookieJs} }` } });
              const ck = await client.callTool({ name: 'browser_evaluate', arguments: { function: '() => document.cookie' } });
              log(name, 'COOKIES', `user=${user} injected ${preCookies.length} cookie(s) for ${preHostname}: ${(ck?.content?.[0]?.text || '').substring(0, 200)}`);
            }
          }

          // browser_wait_for: plain Node.js sleep — no Playwright MCP call needed
          if (name === 'browser_wait_for') {
            const ms = Math.min(toolArgs.time ?? 1000, 30000);
            await new Promise(r => setTimeout(r, ms));
            log(name, 'OK', `user=${user} waited ${ms}ms`);
            return { content: [{ type: 'text', text: `Waited ${ms}ms` }] };
          }

          log(name, 'FORWARD', `user=${user} args=${JSON.stringify(toolArgs)}`);
          let result = await client.callTool({ name: def.playwrightName || name, arguments: toolArgs });
          if (result.isError) {
            const errText = result.content?.[0]?.text || 'unknown error';
            log(name, 'PW-ERROR', `user=${user} ${errText.substring(0, 200)}`);
          } else {
            log(name, 'OK', `user=${user} contentItems=${result.content?.length || 0}`);
          }

          // For browser_take_screenshot: save PNG to disk and append the path as a text content item
          if (name === 'browser_take_screenshot' && !result.isError) {
            const imageItem = result.content?.find(c => c.type === 'image' && c.data);
            if (imageItem) {
              const fname = filename || `${Date.now()}.png`;
              const folder = (job_id && reference_id)
                ? `/workspace/tmp/screenshots/${job_id}-${reference_id}`
                : `/workspace/tmp/screenshots`;
              const filePath = `${folder}/${fname}`;
              try {
                await mkdir(folder, { recursive: true });
                await writeFile(filePath, Buffer.from(imageItem.data, 'base64'));
                log(name, 'SAVED', `user=${user} path=${filePath}`);
                result.content = [
                  ...result.content,
                  { type: 'text', text: `Screenshot saved to: ${filePath}` },
                ];
              } catch (saveErr) {
                log(name, 'WARN', `user=${user} failed to save screenshot: ${saveErr.message}`);
              }
            }
          }

          return result;
        } catch (err) {
          log(name, 'ERROR', `user=${user} ${err.message}`);
          return {
            content: [{ type: 'text', text: `Browser error: ${err.message}` }],
            isError: true,
          };
        }
      },
    );
  }

  // --- Passthrough registration for upstream Playwright tools ---
  const upstreamTools = playwright.getTools();
  for (const tool of upstreamTools) {
    if (!toolWhitelist.includes(tool.name)) continue;
    if (BROWSER_TOOLS[tool.name]) continue; // custom wrapper takes priority

    let zodShape;
    try {
      zodShape = jsonSchemaToZodShape(tool.inputSchema);
    } catch (err) {
      log(tool.name, 'SKIP', `Failed to convert schema: ${err.message}`);
      continue;
    }

    server.tool(tool.name, tool.description || '', zodShape, async (args) => {
      const { user, ...toolArgs } = args;
      const client = playwright.getClient();
      if (!client) {
        log(tool.name, 'ERROR', `user=${user} — Playwright MCP not connected`);
        return {
          content: [{ type: 'text', text: 'Error: Playwright MCP is not available. Browser service may be starting up.' }],
          isError: true,
        };
      }
      try {
        log(tool.name, 'FORWARD', `user=${user} args=${JSON.stringify(toolArgs)}`);
        const result = await client.callTool({ name: tool.name, arguments: toolArgs });
        if (result.isError) {
          log(tool.name, 'PW-ERROR', `user=${user} ${(result.content?.[0]?.text || '').substring(0, 200)}`);
        } else {
          log(tool.name, 'OK', `user=${user} contentItems=${result.content?.length || 0}`);
        }
        return result;
      } catch (err) {
        log(tool.name, 'ERROR', `user=${user} ${err.message}`);
        return {
          content: [{ type: 'text', text: `Browser error: ${err.message}` }],
          isError: true,
        };
      }
    });

    registeredPassthroughNames.push(tool.name);
  }

  if (registeredPassthroughNames.length) {
    log('browser', 'INIT', `Passthrough tools registered: ${registeredPassthroughNames.join(', ')}`);
  }
}
