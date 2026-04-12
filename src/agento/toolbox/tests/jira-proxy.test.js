import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { createJiraProxyHandler } from '../../modules/jira/toolbox/jira-proxy.js';

describe('createJiraProxyHandler', () => {
  const log = vi.fn();
  const validConfig = {
    host: 'https://test.atlassian.net',
    user: 'u@test.com',
    token: 'tok123',
  };

  function mockReqRes(body = {}) {
    const req = { body };
    const res = { status: vi.fn().mockReturnThis(), json: vi.fn() };
    return { req, res };
  }

  beforeEach(() => {
    log.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('rejects missing method/path', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    const { req, res } = mockReqRes({});
    await handler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining('method and path are required') }),
    );
  });

  it('rejects invalid HTTP method', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    const { req, res } = mockReqRes({ method: 'PATCH', path: '/rest/api/3/field' });
    await handler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining('Invalid method') }),
    );
  });

  it('returns 500 when Jira not configured', async () => {
    const handler = createJiraProxyHandler(() => ({ host: null, user: null, token: null }), log);
    const { req, res } = mockReqRes({ method: 'GET', path: '/rest/api/3/field' });
    await handler(req, res);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining('not configured') }),
    );
  });

  it('proxies successful GET with ok: true', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    const mockData = [{ id: 'f1', name: 'Summary' }];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify(mockData)),
    }));

    const { req, res } = mockReqRes({ method: 'GET', path: '/rest/api/3/field' });
    await handler(req, res);

    expect(res.json).toHaveBeenCalledWith({ ok: true, status: 200, data: mockData });

    const [url, opts] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(url).toBe('https://test.atlassian.net/rest/api/3/field');
    expect(opts.headers['Authorization']).toBe(
      `Basic ${Buffer.from('u@test.com:tok123').toString('base64')}`,
    );
  });

  it('proxies Jira error with ok: false', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 403,
      text: () => Promise.resolve(JSON.stringify({ errorMessages: ['Forbidden'] })),
    }));

    const { req, res } = mockReqRes({ method: 'POST', path: '/rest/api/3/field', body: { name: 'Test' } });
    await handler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({
      ok: false, status: 403, data: { errorMessages: ['Forbidden'] },
    });
  });

  it('does not send body on GET requests', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200,
      text: () => Promise.resolve('{}'),
    }));

    const { req, res } = mockReqRes({ method: 'GET', path: '/rest/api/3/field', body: { ignored: true } });
    await handler(req, res);

    const [, opts] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(opts.body).toBeUndefined();
  });

  it('returns 500 on network error', async () => {
    const handler = createJiraProxyHandler(() => validConfig, log);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

    const { req, res } = mockReqRes({ method: 'GET', path: '/rest/api/3/myself' });
    await handler(req, res);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({ error: 'ECONNREFUSED' });
  });
});
