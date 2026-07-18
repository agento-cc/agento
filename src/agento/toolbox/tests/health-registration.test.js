import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('health registration scope isolation', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('resolves default health independently after a scoped registration', async () => {
    const scopedLog = vi.fn();
    const registerTools = vi.fn(async (_server, _context, agentViewId) => ({
      toolNames: [agentViewId ? `scoped_${agentViewId}` : 'default_tool'],
      healthchecks: [agentViewId ? 'scoped_check' : 'default_check'],
    }));
    const loadScopedDbOverrides = vi.fn().mockResolvedValue({
      overrides: { scoped: true },
      agentViewMeta: { id: 7, agentViewCode: 'reviewer' },
    });
    vi.doMock('../config-loader.js', () => ({ registerTools, loadScopedDbOverrides }));
    vi.doMock('../log.js', () => ({ createScopedLogger: () => scopedLog }));

    const { createHealthRegistration } = await import('../health-registration.js');
    const defaultLog = vi.fn();
    const context = { log: defaultLog, sqlPoolRegistry: {} };

    const scoped = await createHealthRegistration(7, context);
    const defaultScope = await createHealthRegistration(null, context);

    expect(scoped).toEqual({ tools: ['scoped_7'], healthchecks: ['scoped_check'] });
    expect(defaultScope).toEqual({ tools: ['default_tool'], healthchecks: ['default_check'] });
    expect(registerTools.mock.calls[0][1].log).toBe(scopedLog);
    expect(registerTools.mock.calls[1][1].log).toBe(defaultLog);
    expect(registerTools.mock.calls.map(call => call[2])).toEqual([7, null]);
  });
});
