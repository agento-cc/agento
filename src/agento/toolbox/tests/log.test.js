import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('node:fs', () => ({
  appendFileSync: vi.fn(),
}));

import { createScopedLogger } from '../log.js';

describe('createScopedLogger', () => {
  beforeEach(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  it('includes agent_view prefix when meta provided', () => {
    const log = createScopedLogger({ id: 42, label: 'Developer' });
    log('mysql_prod', 'OK', 'rows=1');
    const output = console.log.mock.calls[0][0];
    expect(output).toContain('[Developer (id: 42)]');
    expect(output).toContain('[mysql_prod]');
    expect(output).toContain('OK');
    expect(output).toContain('rows=1');
  });

  it('omits prefix when no meta', () => {
    const log = createScopedLogger(null);
    log('mysql_prod', 'OK', 'rows=1');
    const output = console.log.mock.calls[0][0];
    expect(output).not.toContain('(id:');
    expect(output).toContain('[mysql_prod]');
  });

  it('includes ISO timestamp', () => {
    const log = createScopedLogger({ id: 1, label: 'Test' });
    log('tool', 'OK');
    const output = console.log.mock.calls[0][0];
    // ISO timestamp pattern: [2026-03-29T...]
    expect(output).toMatch(/\[\d{4}-\d{2}-\d{2}T/);
  });

  it('handles empty details', () => {
    const log = createScopedLogger({ id: 1, label: 'Test' });
    log('tool', 'OK');
    const output = console.log.mock.calls[0][0];
    expect(output).toContain('[tool] OK ');
  });
});
