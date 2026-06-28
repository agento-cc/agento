import { describe, it, expect, vi } from 'vitest';

import { createBitbucketAuth } from '../../modules/bitbucket/toolbox/bitbucket-auth.js';

const CFG = { bitbucket_workspace: 'acme', bitbucket_email: 'agent@x.com', bitbucket_api_token: 'tok-123' };

function resp(status, headers = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (k) => headers[k.toLowerCase()] ?? null },
    text: async () => '',
    json: async () => ({}),
  };
}

function makeFetch(responses) {
  let i = 0;
  return vi.fn(async () => responses[Math.min(i++, responses.length - 1)]);
}

const noSleep = () => Promise.resolve();

describe('bitbucket-auth: header + URL safety', () => {
  it('builds the Basic auth header from base64(email:token)', () => {
    const auth = createBitbucketAuth(CFG);
    const expected = 'Basic ' + Buffer.from('agent@x.com:tok-123').toString('base64');
    expect(auth.authHeader()).toBe(expected);
  });

  it('isConfigured requires workspace + email + token', () => {
    expect(createBitbucketAuth(CFG).isConfigured()).toBe(true);
    expect(createBitbucketAuth({ bitbucket_workspace: 'acme' }).isConfigured()).toBe(false);
  });

  it('percent-encodes every path segment and builds the query via URLSearchParams', async () => {
    const fetchMock = makeFetch([resp(200)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    await auth.bbFetch(['repositories', 'acme', 'my repo', 'pullrequests'], {
      query: { q: 'author.uuid="{x/y}" AND state="OPEN"' },
    });
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain('/repositories/acme/my%20repo/pullrequests');
    expect(url).toContain('q=author.uuid%3D%22%7Bx%2Fy%7D%22+AND+state%3D%22OPEN%22');
  });

  it('rejects an absolute URL smuggled in as a segment', async () => {
    const auth = createBitbucketAuth(CFG, { fetch: makeFetch([resp(200)]), sleep: noSleep });
    await expect(auth.bbFetch(['https://evil.example.com/x'])).rejects.toThrow(/absolute URL/);
  });

  it('rejects a workspace segment that differs from the configured workspace', async () => {
    const auth = createBitbucketAuth(CFG, { fetch: makeFetch([resp(200)]), sleep: noSleep });
    await expect(
      auth.bbFetch(['repositories', 'other-ws', 'api', 'pullrequests']),
    ).rejects.toThrow(/workspace/);
  });

  it('never leaks the token in a thrown error', async () => {
    const auth = createBitbucketAuth(CFG, { fetch: makeFetch([resp(200)]), sleep: noSleep });
    await auth.bbFetch(['repositories', 'wrong', 'r']).catch((e) => {
      expect(e.message).not.toContain('tok-123');
    });
  });
});

describe('bitbucket-auth: method-aware retry/backoff', () => {
  it('retries a 429 for GET, then succeeds', async () => {
    const fetchMock = makeFetch([resp(429), resp(200)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    const r = await auth.bbFetch(['user']);
    expect(r.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('retries a 429 for POST too (the request was rejected, not processed)', async () => {
    const fetchMock = makeFetch([resp(429), resp(201)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    const r = await auth.bbFetch(['repositories', 'acme', 'api', 'pullrequests'], { method: 'POST', body: {} });
    expect(r.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('retries a 5xx for an idempotent GET', async () => {
    const fetchMock = makeFetch([resp(503), resp(200)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    await auth.bbFetch(['user']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does NOT retry a 5xx on a mutating POST (could duplicate the write)', async () => {
    const fetchMock = makeFetch([resp(500), resp(200)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    const r = await auth.bbFetch(['repositories', 'acme', 'api', 'pullrequests'], { method: 'POST', body: {} });
    expect(r.status).toBe(500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('honors Retry-After (seconds) for the backoff delay', async () => {
    const fetchMock = makeFetch([resp(429, { 'retry-after': '2' }), resp(200)]);
    const sleep = vi.fn(() => Promise.resolve());
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep });
    await auth.bbFetch(['user']);
    expect(sleep).toHaveBeenCalledWith(2000);
  });

  it('gives up after MAX_RETRIES and returns the last response', async () => {
    const fetchMock = makeFetch([resp(429), resp(429), resp(429), resp(429), resp(429)]);
    const auth = createBitbucketAuth(CFG, { fetch: fetchMock, sleep: noSleep });
    const r = await auth.bbFetch(['user']);
    expect(r.status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(4); // initial + 3 retries
  });
});
