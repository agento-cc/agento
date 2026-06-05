import { describe, it, expect, vi } from 'vitest';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCHEDULE_PATH = path.resolve(__dirname, '../../modules/core/toolbox/schedule.js');

function fakeServer() {
  const names = [];
  return { names, tool: (name) => names.push(name) };
}

const ctx = { log: vi.fn(), db: {}, isToolEnabled: () => false };

describe('schedule_followup opt-in gating', () => {
  it('does NOT register when is_enabled is missing/disabled (opt-in)', async () => {
    const { register } = await import(SCHEDULE_PATH);
    const server = fakeServer();
    register(server, { ...ctx, isToolEnabled: () => false });
    expect(server.names).not.toContain('schedule_followup');
  });

  it('registers when explicitly enabled', async () => {
    const { register } = await import(SCHEDULE_PATH);
    const server = fakeServer();
    register(server, { ...ctx, isToolEnabled: (name) => name === 'schedule_followup' });
    expect(server.names).toContain('schedule_followup');
  });
});
