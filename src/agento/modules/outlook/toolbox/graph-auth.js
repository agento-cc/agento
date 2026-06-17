// Microsoft Graph auth. Supports BOTH a client certificate AND a client secret, selected by config
// (per the plan addendum D-A). Uses @azure/identity so the cert (client-assertion JWT) path is handled
// by a battle-tested library rather than hand-rolled crypto. Config comes from the resolved module
// config object (3-level fallback), NOT process.env directly. Secrets live ONLY in the toolbox.

import { ClientSecretCredential, ClientCertificateCredential } from '@azure/identity';

const GRAPH_SCOPE = 'https://graph.microsoft.com/.default';

// `deps` lets tests inject fake credential constructors (default to the real @azure/identity ones).
export function createGraphAuth(cfg = {}, deps = {}) {
  const tenantId = cfg.outlook_tenant_id || null;
  const clientId = cfg.outlook_client_id || null;
  const clientSecret = cfg.outlook_client_secret || null;
  const certPath = cfg.outlook_cert_path || null;
  const mailboxUserId = cfg.outlook_mailbox_user_id || null;

  const makeSecretCredential = deps.makeSecretCredential || ((t, c, s) => new ClientSecretCredential(t, c, s));
  const makeCertCredential =
    deps.makeCertCredential || ((t, c, p) => new ClientCertificateCredential(t, c, { certificatePath: p }));

  let credential = null; // lazily constructed
  let cached = null; // { token, expiresAt (ms epoch) }

  // Certificate takes precedence when both are present (stronger credential).
  function hasCredential() {
    return !!(certPath || clientSecret);
  }

  function isConfigured() {
    return !!(tenantId && clientId && mailboxUserId && hasCredential());
  }

  function getCredential() {
    if (credential) return credential;
    credential = certPath
      ? makeCertCredential(tenantId, clientId, certPath)
      : makeSecretCredential(tenantId, clientId, clientSecret);
    return credential;
  }

  async function getToken() {
    if (!isConfigured()) {
      throw new Error(
        'Graph not configured: set outlook_tenant_id, outlook_client_id, outlook_mailbox_user_id and EITHER outlook_cert_path OR outlook_client_secret'
      );
    }
    const now = Date.now();
    if (cached && cached.expiresAt - 60_000 > now) return cached.token;

    let result;
    try {
      result = await getCredential().getToken(GRAPH_SCOPE);
    } catch (err) {
      // Do NOT surface the raw provider/credential error (it can carry secret/cert detail). A generic
      // message plus the error code is enough to diagnose without leaking material.
      throw new Error(`Graph token acquisition failed (${err.code || err.statusCode || 'auth_error'})`);
    }
    if (!result || !result.token) {
      throw new Error('Graph token acquisition failed (empty token)');
    }
    const expiresAt = result.expiresOnTimestamp || now + 3600 * 1000;
    cached = { token: result.token, expiresAt };
    return cached.token;
  }

  function getMailboxUserId() {
    return mailboxUserId;
  }

  return { isConfigured, getToken, getMailboxUserId };
}
