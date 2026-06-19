import { createGraphAuth } from './graph-auth.js';

const GRAPH_BASE = 'https://graph.microsoft.com/v1.0';

/**
 * Extract the DMARC verdict from a Graph message's internetMessageHeaders.
 *
 * SECURITY: Exchange Online Protection PREPENDS its own authoritative `Authentication-Results`
 * header at inbound ingestion. Any LATER `Authentication-Results` headers may have been supplied
 * by an upstream relay or the sender themselves and MUST NOT be trusted. So we take the FIRST one
 * only (first-header-wins) — trusting a lower, attacker-controllable header would let a spoofer
 * forge `dmarc=pass`.
 *
 * @param {Array<{name:string,value:string}>} headers internetMessageHeaders from Graph
 * @returns {string|null} lowercased verdict ("pass"|"fail"|"none"|...) or null when unavailable
 */
export function parseDmarcVerdict(headers) {
  if (!Array.isArray(headers)) return null;
  const ar = headers.find(
    (h) => h && typeof h.name === 'string' && h.name.toLowerCase() === 'authentication-results'
  );
  if (!ar || typeof ar.value !== 'string') return null;
  const m = ar.value.match(/dmarc=(\w+)/i);
  return m ? m[1].toLowerCase() : null;
}

// configResolver: async (agentViewId) => { cfg, resolved }. `resolved` is false only when a non-null
// id did not match an existing agent_view. `authFactory` is injectable for tests.
export function createUnreadHandler(configResolver, log, authFactory = createGraphAuth) {
  return async (req, res) => {
    const body = req.body || {};
    // Clamp to a safe integer 1..50 — never let NaN / negative values reach the Graph $top query param.
    const rawTop = parseInt(body.top, 10);
    const top = Math.min(Math.max(Number.isFinite(rawTop) ? rawTop : 10, 1), 50);
    const agentViewId = body.agent_view_id ?? null;
    // FAIL-CLOSED: a supplied agent_view_id must be a positive integer (absent/null = global scope).
    if (agentViewId !== null && !(Number.isInteger(agentViewId) && agentViewId > 0)) {
      log('api/outlook/unread', 'ERROR', `invalid agent_view_id=${JSON.stringify(agentViewId)}`);
      return res.status(400).json({ error: 'agent_view_id must be a positive integer' });
    }
    const { cfg, resolved } = await configResolver(agentViewId);
    // FAIL-CLOSED: a supplied id that does not resolve must NOT fall back to the global mailbox
    // (would expose a default mailbox / enable cross-view probing on a bad id).
    if (agentViewId !== null && !resolved) {
      log('api/outlook/unread', 'ERROR', `agent_view_id=${agentViewId} not found`);
      return res.status(404).json({ error: 'agent_view not found' });
    }
    const auth = authFactory(cfg);
    if (!auth.isConfigured()) {
      log('api/outlook/unread', 'ERROR', `agent_view_id=${agentViewId ?? '?'} not configured`);
      return res.status(500).json({ error: 'Graph API not configured' });
    }
    const mailbox = auth.getMailboxUserId(); // resolved, NON-SECRET UPN — returned for the publisher's seen_mailboxes dedupe
    try {
      const token = await auth.getToken();
      const url =
        `${GRAPH_BASE}/users/${encodeURIComponent(mailbox)}/mailFolders/Inbox/messages` +
        `?$filter=isRead eq false` +
        `&$select=id,subject,from,receivedDateTime,conversationId,internetMessageHeaders` +
        `&$orderby=receivedDateTime asc` +
        `&$top=${top}`; // already clamped to 1..50 above
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' } });
      if (!r.ok) {
        // Sanitize: do NOT return/log the raw Graph body (may carry provider internals / mailbox
        // identifiers), especially since this REST route is reachable by any agento-net container.
        await r.text().catch(() => ''); // drain, discard
        log('api/outlook/unread', 'ERROR', `agent_view_id=${agentViewId ?? '?'} Graph unread request failed (HTTP ${r.status})`);
        return res.status(r.status).json({ error: `Graph unread request failed (HTTP ${r.status})` });
      }
      const data = await r.json();
      const messages = (data.value || []).map((m) => ({
        id: m.id,
        subject: m.subject,
        from: { name: m.from?.emailAddress?.name, address: m.from?.emailAddress?.address },
        receivedDateTime: m.receivedDateTime,
        conversationId: m.conversationId,
        dmarc: parseDmarcVerdict(m.internetMessageHeaders),
      }));
      log('api/outlook/unread', 'OK', `agent_view_id=${agentViewId ?? '?'} ${messages.length} unread`);
      return res.json({ mailbox, messages });
    } catch (err) {
      log('api/outlook/unread', 'ERROR', err.message); // server-side cron log only
      return res.status(500).json({ error: 'Internal error fetching unread mail' }); // sanitized to caller
    }
  };
}
