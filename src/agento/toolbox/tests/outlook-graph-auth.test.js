import { describe, it, expect, vi } from 'vitest';
import { createGraphAuth } from '../../modules/outlook/toolbox/graph-auth.js';

const base = { outlook_tenant_id: 'tid', outlook_client_id: 'cid', outlook_mailbox_user_id: 'agent@example.com' };

// Inject fake credential constructors (no real @azure/identity network/file access).
function deps(getToken) {
  const makeSecretCredential = vi.fn(() => ({ getToken }));
  const makeCertCredential = vi.fn(() => ({ getToken }));
  return { makeSecretCredential, makeCertCredential };
}

describe('graph-auth (support both cert and secret)', () => {
  it('isConfigured() is false when no credential (neither cert nor secret)', () => {
    expect(createGraphAuth(base).isConfigured()).toBe(false);
  });

  it('isConfigured() is false when mailbox is missing', () => {
    expect(createGraphAuth({ outlook_tenant_id: 'tid', outlook_client_id: 'cid', outlook_client_secret: 'sec' }).isConfigured()).toBe(false);
  });

  it('uses the secret credential when only a secret is configured', async () => {
    const getToken = vi.fn().mockResolvedValue({ token: 'AAA', expiresOnTimestamp: Date.now() + 3600_000 });
    const d = deps(getToken);
    const a = createGraphAuth({ ...base, outlook_client_secret: 'sec' }, d);
    expect(a.isConfigured()).toBe(true);
    expect(await a.getToken()).toBe('AAA');
    expect(d.makeSecretCredential).toHaveBeenCalledTimes(1);
    expect(d.makeCertCredential).not.toHaveBeenCalled();
  });

  it('uses the certificate credential when a cert is configured (cert wins over secret)', async () => {
    const getToken = vi.fn().mockResolvedValue({ token: 'BBB', expiresOnTimestamp: Date.now() + 3600_000 });
    const d = deps(getToken);
    const a = createGraphAuth({ ...base, outlook_cert_path: '/certs/app.pem', outlook_client_secret: 'sec' }, d);
    expect(a.isConfigured()).toBe(true);
    expect(await a.getToken()).toBe('BBB');
    expect(d.makeCertCredential).toHaveBeenCalledTimes(1);
    expect(d.makeSecretCredential).not.toHaveBeenCalled();
  });

  it('caches the token (no second credential.getToken call before expiry)', async () => {
    const getToken = vi.fn().mockResolvedValue({ token: 'AAA', expiresOnTimestamp: Date.now() + 3600_000 });
    const a = createGraphAuth({ ...base, outlook_client_secret: 'sec' }, deps(getToken));
    await a.getToken();
    await a.getToken();
    expect(getToken).toHaveBeenCalledTimes(1);
  });

  it('throws a sanitized error (code only, no raw provider detail) on token failure', async () => {
    const getToken = vi.fn().mockRejectedValue(Object.assign(new Error('AADSTS7000215: bad client secret'), { code: 'AuthError' }));
    const a = createGraphAuth({ ...base, outlook_client_secret: 'sec' }, deps(getToken));
    await expect(a.getToken()).rejects.toThrow(/Graph token acquisition failed/);
    await expect(a.getToken()).rejects.not.toThrow(/bad client secret/);
  });
});
