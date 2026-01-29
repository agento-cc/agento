import { appendFileSync } from 'node:fs';

const LOG_FILE = process.env.LOG_FILE || '/app/logs/toolbox.log';
const PUBLISHER_LOG_FILE = process.env.PUBLISHER_LOG_FILE || '/app/logs/publisher.log';

function _write(file, tool, status, details = '') {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${tool}] ${status} ${details}`;
  console.log(line);
  try {
    appendFileSync(file, line + '\n');
  } catch { /* file write is best-effort */ }
}

export function logToolbox(tool, status, details = '') {
  _write(LOG_FILE, tool, status, details);
}

export function logPublisher(tool, status, details = '') {
  _write(PUBLISHER_LOG_FILE, tool, status, details);
}

export function createScopedLogger(agentViewMeta) {
  return function scopedLogToolbox(tool, status, details = '') {
    const ts = new Date().toISOString();
    const prefix = agentViewMeta
      ? `[${agentViewMeta.label} (id: ${agentViewMeta.id})] `
      : '';
    const line = `[${ts}] ${prefix}[${tool}] ${status} ${details}`;
    console.log(line);
    try {
      appendFileSync(LOG_FILE, line + '\n');
    } catch { /* best-effort */ }
  };
}
