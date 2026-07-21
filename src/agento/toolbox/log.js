import { appendFileSync } from 'node:fs';

const MCP_LOG_FILE = process.env.MCP_LOG_FILE || '/app/logs/toolbox_mcp.log';
const REST_LOG_FILE = process.env.REST_LOG_FILE || '/app/logs/toolbox_rest.log';
const PUBLISHER_LOG_FILE = process.env.PUBLISHER_LOG_FILE || '/app/logs/publisher.log';

function _write(file, tool, status, details = '') {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${tool}] ${status} ${details}`;
  console.log(line);
  try {
    appendFileSync(file, line + '\n');
  } catch { /* file write is best-effort */ }
}

// Agent MCP tool invocations -> toolbox_mcp.log (kept clean of REST/lifecycle noise).
export function logToolboxMcp(tool, status, details = '') {
  _write(MCP_LOG_FILE, tool, status, details);
}

// REST /api/* calls + lifecycle/discovery/startup noise -> toolbox_rest.log.
export function logToolboxRest(tool, status, details = '') {
  _write(REST_LOG_FILE, tool, status, details);
}

export function logPublisher(tool, status, details = '') {
  _write(PUBLISHER_LOG_FILE, tool, status, details);
}

// Per-session logger for the MCP path: registration-time diagnostics (e.g. a module's
// browser SESSION/INIT emitted from register()) route to toolbox_rest.log, then it flips
// to the given MCP invocation logger so only real tool invocations reach toolbox_mcp.log.
// State is per session (one instance per createServer call), so it is safe under concurrent
// sessions. The flip happens after registration completes and before any handler can run.
export function createPhasedLogger(invocationLog) {
  let invoking = false;
  const log = (tool, status, details = '') => {
    (invoking ? invocationLog : logToolboxRest)(tool, status, details);
  };
  log.toInvocationPhase = () => { invoking = true; };
  return log;
}

// Agent_view-scoped MCP tool logger -> toolbox_mcp.log.
export function createScopedLogger(agentViewMeta) {
  return function scopedLogToolbox(tool, status, details = '') {
    const ts = new Date().toISOString();
    const prefix = agentViewMeta
      ? `[${agentViewMeta.label} (id: ${agentViewMeta.id})] `
      : '';
    const line = `[${ts}] ${prefix}[${tool}] ${status} ${details}`;
    console.log(line);
    try {
      appendFileSync(MCP_LOG_FILE, line + '\n');
    } catch { /* best-effort */ }
  };
}
