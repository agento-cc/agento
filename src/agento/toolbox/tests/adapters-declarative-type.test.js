import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { registerAdapterTools } from '../adapters/index.js';

const server = { tool: () => {} };

let errSpy;
beforeEach(() => { errSpy = vi.spyOn(console, 'error').mockImplementation(() => {}); });
afterEach(() => errSpy.mockRestore());

describe('registerAdapterTools declarative tool types', () => {
  it('does NOT warn "No adapter" for the declarative "mcp" type', () => {
    registerAdapterTools(server, [], new Set(['mcp']), {});
    const warned = errSpy.mock.calls.some((c) => String(c[0]).includes('No adapter for tool type "mcp"'));
    expect(warned).toBe(false);
  });

  it('STILL warns for a genuinely unknown tool type', () => {
    registerAdapterTools(server, [], new Set(['bogus']), {});
    const warned = errSpy.mock.calls.some((c) => String(c[0]).includes('No adapter for tool type "bogus"'));
    expect(warned).toBe(true);
  });
});
