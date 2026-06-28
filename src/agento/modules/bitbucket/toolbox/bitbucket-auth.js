// Bitbucket Cloud REST v2 auth + safe fetch. Basic auth = base64(email:api_token), where the API token
// is an Atlassian API token (app passwords are being removed). Config comes from the resolved, already-
// decrypted scoped module config object — the token lives ONLY in the toolbox, never in the publisher.

const BITBUCKET_BASE = 'https://api.bitbucket.org/2.0';

const MAX_RETRIES = 3;
const BACKOFF_BASE_MS = 500;
const BACKOFF_CAP_MS = 8000;

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// `deps` lets tests inject a fake fetch + a no-op sleep (so retry tests don't actually wait).
export function createBitbucketAuth(cfg = {}, deps = {}) {
  const workspace = cfg.bitbucket_workspace || null;
  const email = cfg.bitbucket_email || null;
  const apiToken = cfg.bitbucket_api_token || null;
  const accountUuid = cfg.bitbucket_account_uuid || null;

  const fetchImpl = deps.fetch || ((...a) => fetch(...a));
  const sleep = deps.sleep || defaultSleep;

  function isConfigured() {
    return !!(workspace && email && apiToken);
  }

  function authHeader() {
    // Buffer is Node-native (the toolbox runtime). Never log/echo this value.
    return 'Basic ' + Buffer.from(`${email}:${apiToken}`).toString('base64');
  }

  function buildQuery(query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query || {})) {
      if (v !== undefined && v !== null) params.append(k, String(v));
    }
    const s = params.toString();
    return s ? `?${s}` : '';
  }

  function buildUrl(segments, query) {
    if (!Array.isArray(segments) || segments.length === 0) {
      throw new Error('bbFetch requires a non-empty path-segment array');
    }
    for (const seg of segments) {
      const s = String(seg);
      // Reject any attempt to smuggle an absolute URL through a segment (SSRF / scope-escape guard).
      if (/:\/\//.test(s) || /^https?:/i.test(s)) {
        throw new Error('bbFetch path segments must not be absolute URLs');
      }
    }
    // Repository sub-resources are `repositories/{workspace}/{repo}/...` — the workspace is fixed by the
    // scoped config; reject a caller-supplied workspace that differs from it.
    if (segments[0] === 'repositories' && segments.length >= 2 && String(segments[1]) !== String(workspace)) {
      throw new Error('bbFetch workspace does not match the configured Bitbucket workspace');
    }
    const path = segments.map((s) => encodeURIComponent(String(s))).join('/');
    return `${BITBUCKET_BASE}/${path}${buildQuery(query)}`;
  }

  function shouldRetry(status, method) {
    if (status === 429) return true; // rejected, not processed → safe to re-issue for any method
    // 5xx may have applied a mutating write before erroring → only retry idempotent GETs.
    if (status >= 500 && String(method).toUpperCase() === 'GET') return true;
    return false;
  }

  function retryDelayMs(res, attempt) {
    const retryAfter = res.headers && typeof res.headers.get === 'function' ? res.headers.get('retry-after') : null;
    if (retryAfter) {
      const secs = parseInt(retryAfter, 10);
      if (Number.isFinite(secs) && secs >= 0) return Math.min(secs * 1000, BACKOFF_CAP_MS);
    }
    return Math.min(BACKOFF_BASE_MS * 2 ** attempt, BACKOFF_CAP_MS);
  }

  // segments: array of path segments (each encodeURIComponent'd). opts: { query, method, body, headers }.
  async function bbFetch(segments, opts = {}) {
    const { query = {}, method = 'GET', body, headers = {} } = opts;
    const url = buildUrl(segments, query);
    const fetchOpts = {
      method,
      headers: { Authorization: authHeader(), Accept: 'application/json', ...headers },
    };
    if (body !== undefined) {
      fetchOpts.body = typeof body === 'string' ? body : JSON.stringify(body);
      fetchOpts.headers['Content-Type'] = 'application/json';
    }

    let attempt = 0;
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const res = await fetchImpl(url, fetchOpts);
      if (shouldRetry(res.status, method) && attempt < MAX_RETRIES) {
        await sleep(retryDelayMs(res, attempt));
        attempt += 1;
        continue;
      }
      return res;
    }
  }

  return {
    isConfigured,
    authHeader,
    bbFetch,
    getWorkspace: () => workspace,
    getAccountUuid: () => accountUuid,
    getEmail: () => email,
  };
}
