/**
 * Jira API proxy handler — extracted for testability.
 *
 * @param {Function|Object} configOrResolver - { host, user, token } or async () => { host, user, token }
 * @param {Function} log - logging function
 * @returns {Function} Express route handler for POST /api/jira/request
 */
export function createJiraProxyHandler(configOrResolver, log) {
  return async (req, res) => {
    const config = typeof configOrResolver === 'function'
      ? await configOrResolver()
      : configOrResolver;

    const { method, path } = req.body;
    const body = req.body.body || null;

    if (!method || !path) {
      return res.status(400).json({ error: 'method and path are required' });
    }

    const ALLOWED_METHODS = ['GET', 'POST', 'PUT', 'DELETE'];
    if (!ALLOWED_METHODS.includes(method.toUpperCase())) {
      return res.status(400).json({ error: `Invalid method: ${method}` });
    }

    const { host } = config;
    // Allow per-request auth override (for admin operations)
    const user = req.body.auth_user || config.user;
    const token = req.body.auth_token || config.token;

    if (!user || !token || !host) {
      return res.status(500).json({ error: 'Jira API not configured (jira_host/jira_user/jira_token)' });
    }

    const auth = Buffer.from(`${user}:${token}`).toString('base64');
    const upperMethod = method.toUpperCase();
    const fetchOptions = {
      method: upperMethod,
      headers: {
        'Authorization': `Basic ${auth}`,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
    };
    if (body && upperMethod !== 'GET') {
      fetchOptions.body = JSON.stringify(body);
    }

    try {
      const response = await fetch(`${host}${path}`, fetchOptions);
      const text = await response.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }

      if (!response.ok) {
        log('api/jira/request', 'ERROR', `${method} ${path} -> HTTP ${response.status}`);
        return res.status(200).json({ ok: false, status: response.status, data });
      }

      log('api/jira/request', 'OK', `${method} ${path} -> ${response.status}`);
      res.json({ ok: true, status: response.status, data });
    } catch (err) {
      log('api/jira/request', 'ERROR', err.message);
      res.status(500).json({ error: err.message });
    }
  };
}
