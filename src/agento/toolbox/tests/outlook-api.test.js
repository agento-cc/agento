import { describe, it, expect, vi, beforeEach } from 'vitest';

import { createUnreadHandler, parseDmarcVerdict } from '../../modules/outlook/toolbox/api-handlers.js';

// Inject a fake auth so token acquisition needs no real @azure/identity; the only global fetch the
// handler makes is the Graph messages call. isConfigured mirrors graph-auth's real rule.
const fakeAuthFactory = (cfg) => ({
  isConfigured: () => !!(cfg.outlook_tenant_id && cfg.outlook_client_id && cfg.outlook_mailbox_user_id && (cfg.outlook_cert_pem || cfg.outlook_client_secret)),
  getToken: async () => 'AAA',
  getMailboxUserId: () => cfg.outlook_mailbox_user_id,
});

function mockRes() {
  return {
    statusCode: 200,
    body: null,
    status(c) { this.statusCode = c; return this; },
    json(b) { this.body = b; return this; },
  };
}

const cfg = {
  outlook_tenant_id: 'tid', outlook_client_id: 'cid',
  outlook_client_secret: 'sec', outlook_mailbox_user_id: 'agent@example.com',
};

describe('parseDmarcVerdict (first Authentication-Results header wins — anti-spoof)', () => {
  it('returns "pass" for a passing first header', () => {
    expect(parseDmarcVerdict([
      { name: 'Authentication-Results', value: 'spf=pass; dkim=pass; dmarc=pass action=none header.from=mycompanystudio.com' },
    ])).toBe('pass');
  });

  it('returns "fail" for a failing header', () => {
    expect(parseDmarcVerdict([{ name: 'Authentication-Results', value: 'dmarc=fail action=oreject' }])).toBe('fail');
  });

  it('is case-insensitive on header name and verdict', () => {
    expect(parseDmarcVerdict([{ name: 'authentication-results', value: 'DMARC=Pass' }])).toBe('pass');
  });

  it('returns null when there is no Authentication-Results header / no dmarc token', () => {
    expect(parseDmarcVerdict([{ name: 'Received', value: 'from mail.x.com' }])).toBeNull();
    expect(parseDmarcVerdict([])).toBeNull();
    expect(parseDmarcVerdict(undefined)).toBeNull();
    expect(parseDmarcVerdict([{ name: 'Authentication-Results', value: 'spf=pass; dkim=pass' }])).toBeNull();
  });

  it('ANTI-SPOOF: a later injected dmarc=pass header does NOT override a failing first header', () => {
    expect(parseDmarcVerdict([
      { name: 'Authentication-Results', value: 'dmarc=fail' },        // EOP-stamped, trusted, FIRST
      { name: 'Authentication-Results', value: 'dmarc=pass' },        // attacker-injected, lower, ignored
    ])).toBe('fail');
  });
});

const ok = (c) => async () => ({ cfg: c, resolved: true });

describe('POST /api/outlook/unread handler', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('returns 500 when not configured', async () => {
    const handler = createUnreadHandler(ok({}), vi.fn(), fakeAuthFactory);
    const res = mockRes();
    await handler({ body: {} }, res);
    expect(res.statusCode).toBe(500);
  });

  it('returns { mailbox, messages } with the resolved UPN and maps Graph fields', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ value: [
        { id: 'm1', subject: 'A', from: { emailAddress: { address: 'x@y.com', name: 'X' } },
          receivedDateTime: '2026-01-01T00:00:00Z', conversationId: 'c1',
          internetMessageHeaders: [{ name: 'Authentication-Results', value: 'dmarc=pass' }] },
      ] }),
    }));
    const handler = createUnreadHandler(ok(cfg), vi.fn(), fakeAuthFactory);
    const res = mockRes();
    await handler({ body: { top: 10 } }, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.mailbox).toBe('agent@example.com');
    expect(res.body.messages).toHaveLength(1);
    expect(res.body.messages[0]).toMatchObject({ id: 'm1', subject: 'A', dmarc: 'pass' });
    expect(res.body.messages[0].from.address).toBe('x@y.com');
  });

  it('forwards agent_view_id from the body to the config resolver', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ value: [] }) }));
    const resolver = vi.fn(async () => ({ cfg, resolved: true }));
    const handler = createUnreadHandler(resolver, vi.fn(), fakeAuthFactory);
    await handler({ body: { top: 5, agent_view_id: 42 } }, mockRes());
    expect(resolver).toHaveBeenCalledWith(42);
  });

  it('passes null to the resolver when agent_view_id is absent (global scope)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ value: [] }) }));
    const resolver = vi.fn(async () => ({ cfg, resolved: true }));
    const handler = createUnreadHandler(resolver, vi.fn(), fakeAuthFactory);
    await handler({ body: { top: 5 } }, mockRes());
    expect(resolver).toHaveBeenCalledWith(null);
  });

  it('FAIL-CLOSED: rejects a non-positive-integer agent_view_id with 400 (no resolver/Graph call)', async () => {
    const resolver = vi.fn(ok(cfg));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const handler = createUnreadHandler(resolver, vi.fn(), fakeAuthFactory);
    for (const bad of ['7', 0, -1, 1.5]) {
      const res = mockRes();
      await handler({ body: { agent_view_id: bad } }, res);
      expect(res.statusCode).toBe(400);
    }
    expect(resolver).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('FAIL-CLOSED: returns 404 (no global fallback) when a supplied id does not resolve', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const handler = createUnreadHandler(async () => ({ cfg, resolved: false }), vi.fn(), fakeAuthFactory);
    const res = mockRes();
    await handler({ body: { agent_view_id: 999 } }, res);
    expect(res.statusCode).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requests internetMessageHeaders and clamps a bogus top (>50) to 1..50', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ value: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const handler = createUnreadHandler(ok(cfg), vi.fn(), fakeAuthFactory);
    await handler({ body: { top: 999 } }, mockRes());
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain('internetMessageHeaders');
    expect(url).toContain('$top=50');
    expect(url).not.toMatch(/\$top=(NaN|-)/);
  });
});
