import { describe, it, expect, vi, beforeEach } from 'vitest';

import { register, matchesWhitelist } from '../../modules/outlook/toolbox/outlook.js';

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

// The read tools surface a message only if it is allow-listed AND passes DMARC, so mocked Graph
// messages that should be readable must carry a passing Authentication-Results header.
const PASS_DMARC = [{ name: 'Authentication-Results', value: 'spf=pass; dkim=pass; dmarc=pass' }];
const FAIL_DMARC = [{ name: 'Authentication-Results', value: 'spf=fail; dmarc=fail' }];

function ctx(overrides = {}) {
  return {
    log: vi.fn(),
    moduleConfigs: { outlook: cfg, core: { email_whitelist: 'sklep@mycompanystudio.com, *@mycompany.com' } },
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
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ from: { emailAddress: { address: 'sklep@mycompanystudio.com' } } }) })
      .mockResolvedValueOnce({ ok: true, text: () => Promise.resolve('') });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_reply.handler({ message_id: 'm1', body: '<p>hi</p>' });
    expect(r.isError).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('/reply');
    expect(fetchMock.mock.calls[1][1].method).toBe('POST');
    // The reply is sent as an HTML message.body — NOT the plain-text `comment` param (mutually
    // exclusive in Graph; sending both = HTTP 400). Lock the body shape against a regression.
    const sent = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(sent.message.body.contentType).toBe('HTML');
    expect(sent.message.body.content).toBe('<p>hi</p>');
    expect(sent.comment).toBeUndefined();
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

describe('read restriction (restrict_read_to_allowed_senders)', () => {
  // Gate the read tools by outlook/allowed_senders so an enabled read tool can't surface mail the
  // channel would never have created a job for. Default ON; empty allowed_senders = block all.
  function ctxRead(allowed, restrict) {
    const outlook = { ...cfg, allowed_senders: allowed };
    if (restrict !== undefined) outlook.restrict_read_to_allowed_senders = restrict;
    return { log: vi.fn(), moduleConfigs: { outlook, core: {} }, isToolEnabled: () => true, graphAuthFactory };
  }

  it('outlook_get_message BLOCKS a message from a non-allow-listed sender (default on)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'stranger@evil.com' } } }) }));
    const s = makeServer();
    register(s, ctxRead('sklep@mycompanystudio.com'));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
  });

  it('outlook_get_message ALLOWS a message from an allow-listed, DMARC-passing sender', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } }, internetMessageHeaders: PASS_DMARC }) }));
    const s = makeServer();
    register(s, ctxRead('sklep@mycompanystudio.com'));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBeUndefined();
  });

  it('outlook_get_message returns even a non-allow-listed sender when restriction is OFF', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'stranger@evil.com' } } }) }));
    const s = makeServer();
    register(s, ctxRead('sklep@mycompanystudio.com', false));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBeUndefined();
  });

  it('outlook_search_messages / outlook_get_new_messages filter out non-allow-listed senders', async () => {
    const value = [
      { id: 'a', subject: 'A', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } }, receivedDateTime: 't', isRead: false, internetMessageHeaders: PASS_DMARC },
      { id: 'b', subject: 'B', from: { emailAddress: { address: 'stranger@evil.com' } }, receivedDateTime: 't', isRead: false, internetMessageHeaders: PASS_DMARC },
      { id: 'c', subject: 'C', from: { emailAddress: { address: 'anyone@mycompany.com' } }, receivedDateTime: 't', isRead: false, internetMessageHeaders: PASS_DMARC },
    ];
    for (const tool of ['outlook_search_messages', 'outlook_get_new_messages']) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ value }) }));
      const s = makeServer();
      register(s, ctxRead('sklep@mycompanystudio.com, *@mycompany.com'));
      const r = await s.tools[tool].handler({ folder: 'inbox' });
      const out = JSON.parse(r.content[0].text);
      const ids = out.map((m) => m.message_id).sort();
      expect(ids).toEqual(['a', 'c']); // stranger@evil.com filtered out
      // contract: `from` stays the address STRING (not an object) — filtering must not change the shape
      expect(out.every((m) => typeof m.from === 'string')).toBe(true);
    }
  });

  it('empty allowed_senders blocks all reads (fail-closed) when restriction is on', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } } }) }));
    const s = makeServer();
    register(s, ctxRead(''));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
  });
});

describe('MCP tools target the per-agent_view mailbox (no code change — scoped moduleConfigs)', () => {
  // The toolbox scopes a session's moduleConfigs to the job's agent_view_id (registerTools ->
  // loadScopedDbOverrides). graph-auth derives the mailbox from the config it is built with, so the
  // mailbox in moduleConfigs.outlook is the one the Graph URL hits. Mirror that here.
  const scopedAuthFactory = (c) => ({
    isConfigured: () => true,
    getToken: async () => 'AAA',
    getMailboxUserId: () => c.outlook_mailbox_user_id,
  });

  function ctxForView(mailbox) {
    return {
      log: vi.fn(),
      moduleConfigs: {
        outlook: { ...cfg, outlook_mailbox_user_id: mailbox },
        core: { email_whitelist: 'sklep@mycompanystudio.com, *@mycompany.com' },
      },
      isToolEnabled: () => true,
      graphAuthFactory: scopedAuthFactory,
    };
  }

  it('outlook_reply for a job under view X sends to view X mailbox; view Y uses view Y mailbox', async () => {
    const fetchMock = vi.fn()
      // view X: $select=from lookup (whitelisted) then /reply POST
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ from: { emailAddress: { address: 'sklep@mycompanystudio.com' } } }) })
      .mockResolvedValueOnce({ ok: true, text: () => Promise.resolve('') })
      // view Y: same
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ from: { emailAddress: { address: 'sklep@mycompanystudio.com' } } }) })
      .mockResolvedValueOnce({ ok: true, text: () => Promise.resolve('') });
    vi.stubGlobal('fetch', fetchMock);

    const sx = makeServer();
    register(sx, ctxForView('viewx@example.com'));
    await sx.tools.outlook_reply.handler({ message_id: 'mX', body: 'hi' });

    const sy = makeServer();
    register(sy, ctxForView('viewy@example.com'));
    await sy.tools.outlook_reply.handler({ message_id: 'mY', body: 'hi' });

    // calls[1] is view X's /reply, calls[3] is view Y's /reply
    expect(fetchMock.mock.calls[1][0]).toContain('/users/viewx%40example.com/');
    expect(fetchMock.mock.calls[3][0]).toContain('/users/viewy%40example.com/');
  });

  it('outlook_mark_processed PATCHes the per-view mailbox message', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxForView('viewz@example.com'));
    await s.tools.outlook_mark_processed.handler({ message_id: 'm1' });
    expect(fetchMock.mock.calls[0][0]).toContain('/users/viewz%40example.com/messages/');
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH');
  });
});

// ctx whose outlook config carries allowed_senders (for the S3 read-restriction tests).
function ctxWithOutlook(outlookOverrides = {}) {
  return {
    log: vi.fn(),
    moduleConfigs: {
      outlook: { ...cfg, allowed_senders: 'sklep@mycompanystudio.com, *@mycompany.com', ...outlookOverrides },
      core: { email_whitelist: 'sklep@mycompanystudio.com, *@mycompany.com' },
    },
    isToolEnabled: () => true,
    graphAuthFactory,
  };
}

describe('S1: Graph error bodies are sanitized (no provider internals leak to the agent)', () => {
  it('outlook_get_message returns a status-only error, never the raw Graph body', async () => {
    const leak = 'SECRET mailbox=victim@corp.com tenant=11111111-2222 x-ms-diagnostics=internal-detail';
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, text: () => Promise.resolve(leak) });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
    const text = r.content[0].text;
    expect(text).toContain('404');
    expect(text).not.toContain('SECRET');
    expect(text).not.toContain('victim@corp.com');
    expect(text).not.toContain('x-ms-diagnostics');
  });

  it('outlook_send_mail returns a status-only error on a Graph failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500, text: () => Promise.resolve('SECRET tenant detail') });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_send_mail.handler({ to: ['sklep@mycompanystudio.com'], subject: 'x', body: 'y' });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).toContain('500');
    expect(r.content[0].text).not.toContain('SECRET');
  });
});

describe('S3: read tools are restricted to allowed_senders (default on)', () => {
  const okMsg = (addr, headers = PASS_DMARC) => ({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: addr } }, internetMessageHeaders: headers }) });
  const listOf = (...addrs) => ({
    ok: true,
    json: () => Promise.resolve({ value: addrs.map((a, i) => ({ id: String(i + 1), subject: 's', from: { emailAddress: { address: a } }, internetMessageHeaders: PASS_DMARC })) }),
  });

  it('outlook_get_message BLOCKS (and withholds the body of) a non-allow-listed sender', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okMsg('stranger@evil.com')));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).not.toContain('"subject"'); // result object never serialized
  });

  it('outlook_get_message ALLOWS an allow-listed sender', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okMsg('sklep@mycompanystudio.com')));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBeUndefined();
    expect(r.content[0].text).toContain('sklep@mycompanystudio.com');
  });

  it('outlook_get_message returns any sender when the restriction is disabled', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okMsg('stranger@evil.com')));
    const s = makeServer();
    register(s, ctxWithOutlook({ restrict_read_to_allowed_senders: false }));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBeUndefined();
    expect(r.content[0].text).toContain('stranger@evil.com');
  });

  it('outlook_search_messages filters out non-allow-listed senders', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(listOf('sklep@mycompanystudio.com', 'stranger@evil.com', 'bob@mycompany.com')));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_search_messages.handler({ folder: 'inbox' });
    const out = JSON.parse(r.content[0].text);
    expect(out.map((m) => m.message_id).sort()).toEqual(['1', '3']);
    expect(JSON.stringify(out)).not.toContain('stranger@evil.com');
  });

  it('outlook_get_new_messages filters out non-allow-listed senders', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(listOf('sklep@mycompanystudio.com', 'stranger@evil.com')));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_new_messages.handler({});
    expect(JSON.parse(r.content[0].text).map((m) => m.message_id)).toEqual(['1']);
  });

  it('empty allowed_senders blocks all reads (fail-closed) while restriction is on', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(listOf('sklep@mycompanystudio.com')));
    const s = makeServer();
    register(s, ctxWithOutlook({ allowed_senders: '' }));
    const r = await s.tools.outlook_get_new_messages.handler({});
    expect(JSON.parse(r.content[0].text)).toEqual([]);
  });

  // --- DMARC gate: an allow-listed From is forgeable; the read tools require a DMARC pass too,
  //     mirroring the publisher, so a spoofed allow-listed sender can't be read (prompt-injection). ---

  it('ANTI-SPOOF: outlook_get_message BLOCKS an allow-listed sender that FAILS DMARC', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okMsg('sklep@mycompanystudio.com', FAIL_DMARC)));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).not.toContain('"subject"'); // body withheld
  });

  it('FAIL-CLOSED: outlook_get_message BLOCKS an allow-listed sender with NO DMARC header', async () => {
    // No internetMessageHeaders at all → verdict undeterminable → not surfaced.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ subject: 'S', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } } }) }));
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
  });

  it('ANTI-SPOOF: search / get_new drop an allow-listed sender that fails DMARC, keep the passing one', async () => {
    const mixed = {
      ok: true,
      json: () => Promise.resolve({ value: [
        { id: '1', subject: 's', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } }, internetMessageHeaders: PASS_DMARC },
        { id: '2', subject: 's', from: { emailAddress: { address: 'sklep@mycompanystudio.com' } }, internetMessageHeaders: FAIL_DMARC }, // spoofed allow-listed From
        { id: '3', subject: 's', from: { emailAddress: { address: 'bob@mycompany.com' } } }, // no headers → fail-closed
      ] }),
    };
    for (const tool of ['outlook_search_messages', 'outlook_get_new_messages']) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mixed));
      const s = makeServer();
      register(s, ctxWithOutlook());
      const r = await s.tools[tool].handler({ folder: 'inbox' });
      expect(JSON.parse(r.content[0].text).map((m) => m.message_id)).toEqual(['1']);
    }
  });

  it('read tools request internetMessageHeaders so DMARC can be evaluated', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okMsg('sklep@mycompanystudio.com'));
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(fetchMock.mock.calls[0][0]).toContain('internetMessageHeaders');
  });

  it('restriction OFF bypasses the DMARC gate too (documented security risk)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okMsg('stranger@evil.com', FAIL_DMARC)));
    const s = makeServer();
    register(s, ctxWithOutlook({ restrict_read_to_allowed_senders: false }));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBeUndefined();
  });

  // --- DMARC hydration: a Graph message COLLECTION doesn't reliably return internetMessageHeaders, so
  //     the list tools hydrate the verdict per-message when the collection omits it. ---

  const listNoHeaders = (...addrs) => ({
    ok: true,
    json: () => Promise.resolve({ value: addrs.map((a, i) => ({ id: String(i + 1), subject: 's', from: { emailAddress: { address: a } } })) }),
  });

  it('hydrates DMARC via a per-message GET when the list omits internetMessageHeaders', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listNoHeaders('sklep@mycompanystudio.com'))            // list: no headers inline
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ internetMessageHeaders: PASS_DMARC }) }); // hydration GET
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_new_messages.handler({});
    expect(JSON.parse(r.content[0].text).map((m) => m.message_id)).toEqual(['1']);
    expect(fetchMock.mock.calls[1][0]).toContain('/messages/1');
    expect(fetchMock.mock.calls[1][0]).toContain('internetMessageHeaders');
  });

  it('FAIL-CLOSED: drops a message when DMARC hydration fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listNoHeaders('sklep@mycompanystudio.com'))
      .mockResolvedValueOnce({ ok: false, status: 500, text: () => Promise.resolve('') }); // hydration fails
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_search_messages.handler({ folder: 'inbox' });
    expect(JSON.parse(r.content[0].text)).toEqual([]);
  });

  it('does NOT hydrate DMARC for a non-allow-listed sender (cheap short-circuit, no extra GET)', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(listNoHeaders('stranger@evil.com'));
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctxWithOutlook());
    const r = await s.tools.outlook_get_new_messages.handler({});
    expect(JSON.parse(r.content[0].text)).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the list; the non-allow-listed sender is dropped before hydration
  });
});

describe('matchesWhitelist semantics (S2: full metachar escaping)', () => {
  it('empty whitelist blocks all (fail-closed)', () => {
    expect(matchesWhitelist('anyone@x.com', [])).toBe(false);
  });

  it('wildcard matches any local part but never crosses @', () => {
    const wl = ['*@mycompany.com'];
    expect(matchesWhitelist('bob@mycompany.com', wl)).toBe(true);
    expect(matchesWhitelist('evil@sub.mycompany.com', wl)).toBe(false);
  });

  it('is case-insensitive', () => {
    expect(matchesWhitelist('Bob@Mycompany.com', ['bob@mycompany.com'])).toBe(true);
  });

  it("escapes '?' (literal, not a quantifier) — closes the fail-open widening", () => {
    const wl = ['a?b@x.com'];
    expect(matchesWhitelist('a?b@x.com', wl)).toBe(true);
    expect(matchesWhitelist('b@x.com', wl)).toBe(false);
  });

  it('escapes regex metachars in the local part', () => {
    expect(matchesWhitelist('a.b+c@x.com', ['a.b+c@x.com'])).toBe(true);
    expect(matchesWhitelist('axbxc@x.com', ['a.b+c@x.com'])).toBe(false);
  });
});

describe('outlook_send_mail allow path + cc', () => {
  it('sends when every to/cc recipient is whitelisted (POST body carries to+cc)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_send_mail.handler({
      to: ['sklep@mycompanystudio.com'], cc: ['bob@mycompany.com'], subject: 'x', body: 'y',
    });
    expect(r.isError).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/sendMail');
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.message.toRecipients[0].emailAddress.address).toBe('sklep@mycompanystudio.com');
    expect(sent.message.ccRecipients[0].emailAddress.address).toBe('bob@mycompany.com');
    expect(sent.message.body.contentType).toBe('HTML'); // sent as HTML, not plain text
  });

  it('blocks the whole send when any cc recipient is not whitelisted', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx());
    const r = await s.tools.outlook_send_mail.handler({
      to: ['sklep@mycompanystudio.com'], cc: ['stranger@evil.com'], subject: 'x', body: 'y',
    });
    expect(r.isError).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('tools fail closed when Graph is not configured', () => {
  const unconfigured = () => ({ isConfigured: () => false, getToken: async () => 'AAA', getMailboxUserId: () => 'agent@example.com' });
  for (const name of [
    'outlook_get_message', 'outlook_reply', 'outlook_search_messages',
    'outlook_get_new_messages', 'outlook_send_mail', 'outlook_mark_processed',
  ]) {
    it(`${name} returns isError and issues no Graph call when not configured`, async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);
      const s = makeServer();
      register(s, ctx({ graphAuthFactory: unconfigured }));
      const r = await s.tools[name].handler({ message_id: 'm1', body: 'b', subject: 's', to: ['sklep@mycompanystudio.com'] });
      expect(r.isError).toBe(true);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  }
});

describe('a getToken rejection surfaced through a tool stays sanitized', () => {
  it('outlook_get_message returns isError without raw credential detail (and makes no Graph call)', async () => {
    const auth = () => ({
      isConfigured: () => true,
      getToken: async () => { throw new Error('Graph token acquisition failed (AuthError)'); },
      getMailboxUserId: () => 'agent@example.com',
    });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const s = makeServer();
    register(s, ctx({ graphAuthFactory: auth }));
    const r = await s.tools.outlook_get_message.handler({ message_id: 'm1' });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).not.toMatch(/client secret|AADSTS|private key/i);
    expect(fetchMock).not.toHaveBeenCalled(); // token acquisition failed before any Graph HTTP call
  });
});
