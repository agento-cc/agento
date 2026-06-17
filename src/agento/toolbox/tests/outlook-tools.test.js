import { describe, it, expect, vi, beforeEach } from 'vitest';

import { register } from '../../modules/outlook/toolbox/outlook.js';

// Inject a fake graph-auth so no real @azure/identity is needed; Graph HTTP is stubbed via global fetch.
const graphAuthFactory = () => ({
  isConfigured: () => true,
  getToken: async () => 'AAA',
  getMailboxUserId: () => 'agent@example.com',
});

function makeServer() {
  const tools = {};
  return {
    tools,
    tool(name, desc, schema, handler) { tools[name] = { desc, schema, handler }; },
  };
}

const cfg = {
  outlook_tenant_id: 'tid', outlook_client_id: 'cid',
  outlook_client_secret: 'sec', outlook_mailbox_user_id: 'agent@example.com',
};

function ctx(overrides = {}) {
  return {
    log: vi.fn(),
    moduleConfigs: { outlook: cfg, core: { email_whitelist: 'sklep@kazarstudio.com, *@kazar.com' } },
    isToolEnabled: () => true,
    graphAuthFactory,
    ...overrides,
  };
}

beforeEach(() => vi.unstubAllGlobals());

describe('outlook tools registration + gating', () => {
  it('registers all 6 tools when enabled', () => {
    const s = makeServer();
    register(s, ctx());
    expect(Object.keys(s.tools).sort()).toEqual([
      'outlook_get_message', 'outlook_get_new_messages', 'outlook_mark_processed',
      'outlook_reply', 'outlook_search_messages', 'outlook_send_mail',
    ]);
  });

  it('skips a tool whose is_enabled resolves false (opt-in)', () => {
    const s = makeServer();
    register(s, ctx({ isToolEnabled: (n) => n !== 'outlook_send_mail' }));
    expect(s.tools.outlook_send_mail).toBeUndefined();
    expect(s.tools.outlook_get_message).toBeDefined();
  });

  it('does NOT expose an agent-controlled `user` param (dropped for hardening)', () => {
    const s = makeServer();
    register(s, ctx());
    expect(Object.keys(s.tools.outlook_get_message.schema)).not.toContain('user');
    expect(Object.keys(s.tools.outlook_send_mail.schema)).not.toContain('user');
  });
});

describe('outlook_get_message URL safety', () => {
  it('percent-encodes a message_id containing /, +, = in the Graph URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'a@b.com' } } }) });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    await s.tools.outlook_get_message.handler({ message_id: 'AA/BB+CC=DD' });
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain('AA%2FBB%2BCC%3DDD');
    expect(url).not.toContain('AA/BB+CC=DD');
  });
});

describe('outlook_reply recipient whitelist', () => {
  it('BLOCKS a reply when the original sender is not whitelisted (no reply POST issued)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ from: { emailAddress: { address: 'stranger@evil.com' } } }) });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_reply.handler({ message_id: 'm1', body: 'hi' });
    expect(r.isError).toBe(true);
    // only the $select=from lookup happened; no /reply POST
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('$select=from');
  });

  it('ALLOWS a reply when the original sender is whitelisted (reply POST issued)', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ from: { emailAddress: { address: 'sklep@kazarstudio.com' } } }) })
      .mockResolvedValueOnce({ ok: true, text: () => Promise.resolve('') });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_reply.handler({ message_id: 'm1', body: 'hi' });
    expect(r.isError).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('/reply');
    expect(fetchMock.mock.calls[1][1].method).toBe('POST');
  });
});

describe('outlook_send_mail recipient whitelist', () => {
  it('BLOCKS sending to a non-whitelisted recipient (no sendMail issued)', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_send_mail.handler({ to: ['stranger@evil.com'], subject: 'x', body: 'y' });
    expect(r.isError).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('outlook_search_messages input validation', () => {
  it('rejects a non-ISO-8601 received_after without issuing a request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_search_messages.handler({ folder: 'inbox', received_after: "2026 OR '1'='1" });
    expect(r.isError).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
