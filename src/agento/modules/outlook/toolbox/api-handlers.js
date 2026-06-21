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
  // Anchor to a real Authentication-Results token boundary (start-of-string, whitespace, or ';') so a
  // literal "dmarc=pass" substring inside an attacker-influenced field (a quoted local-part, smtp.helo,
  // etc.) or a different key (x-dmarc=) can't forge a pass — we must read the actual `dmarc` method.
  const m = ar.value.match(/(?:^|[\s;])dmarc=(\w+)/i);
  return m ? m[1].toLowerCase() : null;
}

const DELTA_SELECT = 'id,subject,from,receivedDateTime,conversationId,internetMessageHeaders';

// Host-only guard for the ONE full URL we follow that comes from Graph itself (@odata.nextLink):
// https + graph.microsoft.com + no embedded credentials. Mirrors core/toolbox/browser.js.
function isGraphUrl(u) {
  try {
    const p = new URL(u);
    return p.protocol === 'https:' && p.hostname.toLowerCase() === 'graph.microsoft.com' && !p.username && !p.password;
  } catch {
    return false;
  }
}

// A stored deltaLink is replayed AS-IS (Graph's documented contract). Because it comes from the request
// body and is fetched WITH the Graph app token (which can read ANY mailbox), prove first that it is a
// messages/delta CURSOR for THIS resolved mailbox: we addressed Graph by /users/{UPN}/…, and Graph echoes
// that user segment (the "Inbox" folder is resolved to an opaque folder id, left unconstrained). It must
// also carry a $deltatoken (a real cursor, not an arbitrary delta URL). Total: never throws — a malformed
// URL or malformed %-encoding returns false so the caller falls back to a full base enumeration.
function deltaLinkForMailbox(u, mailbox) {
  if (typeof u !== 'string') return false;
  let p;
  try {
    p = new URL(u);
  } catch {
    return false;
  }
  if (p.protocol !== 'https:' || p.hostname.toLowerCase() !== 'graph.microsoft.com' || p.username || p.password) return false;
  if (!p.searchParams.get('$deltatoken')) return false;
  const m = p.pathname.match(/^\/v1\.0\/users\/([^/]+)\/mailfolders\/[^/]+\/messages\/(?:microsoft\.graph\.)?delta$/i);
  if (!m) return false;
  let seg;
  try {
    seg = decodeURIComponent(m[1]);
  } catch {
    return false;
  }
  return seg.trim().toLowerCase() === (mailbox || '').trim().toLowerCase();
}

function baseDeltaUrl(mailbox, top) {
  return (
    `${GRAPH_BASE}/users/${encodeURIComponent(mailbox)}/mailFolders/Inbox/messages/delta` +
    `?$select=${DELTA_SELECT}&$top=${top}`
  );
}

// configResolver: async (agentViewId) => { cfg, resolved }. `resolved` is false only when a non-null
// id did not match an existing agent_view. `authFactory` is injectable for tests.
export function createDeltaHandler(configResolver, log, authFactory = createGraphAuth) {
  return async (req, res) => {
    const body = req.body || {};
    // Clamp to a safe integer 1..50 — never let NaN / negative values reach the Graph $top query param.
    const rawTop = parseInt(body.top, 10);
    const top = Math.min(Math.max(Number.isFinite(rawTop) ? rawTop : 10, 1), 50);
    const agentViewId = body.agent_view_id ?? null;
    // FAIL-CLOSED: a supplied agent_view_id must be a positive integer (absent/null = global scope).
    if (agentViewId !== null && !(Number.isInteger(agentViewId) && agentViewId > 0)) {
      log('api/outlook/delta', 'ERROR', `invalid agent_view_id=${JSON.stringify(agentViewId)}`);
      return res.status(400).json({ error: 'agent_view_id must be a positive integer' });
    }
    const { cfg, resolved } = await configResolver(agentViewId);
    // FAIL-CLOSED: a supplied id that does not resolve must NOT fall back to the global mailbox.
    if (agentViewId !== null && !resolved) {
      log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId} not found`);
      return res.status(404).json({ error: 'agent_view not found' });
    }
    const auth = authFactory(cfg);
    if (!auth.isConfigured()) {
      log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId ?? '?'} not configured`);
      return res.status(500).json({ error: 'Graph API not configured' });
    }
    const mailbox = auth.getMailboxUserId(); // resolved, NON-SECRET UPN — returned for the publisher's seen_mailboxes dedupe
    const mailboxKey = (mailbox || '').trim().toLowerCase(); // match Python cursor key .strip().lower()
    const cursors = body.cursors && typeof body.cursors === 'object' && !Array.isArray(body.cursors) ? body.cursors : {};
    const rawCursor = cursors[mailboxKey];
    // Use the stored deltaLink only if it validates as THIS mailbox's delta cursor; else full base enum.
    const validCursor = deltaLinkForMailbox(rawCursor, mailbox) ? rawCursor : null;

    try {
      const token = await auth.getToken();
      const authHeaders = { Authorization: `Bearer ${token}`, Accept: 'application/json' };

      let url, resynced;
      if (validCursor) {
        url = validCursor;
        resynced = false;
      } else {
        url = baseDeltaUrl(mailbox, top);
        resynced = typeof rawCursor === 'string' && rawCursor.length > 0; // had a cursor but it was unusable -> full re-enum
      }

      const raw = [];
      let deltaLink = null;

      // Page to the end. On a 410 OR a 40x carrying syncStateNotFound/resyncRequired (stale/expired
      // cursor), restart ONCE from the base URL (fail-closed full re-enumeration). Generous page cap
      // guards against a pathological loop.
      for (let page = 0; page < 1000; page++) {
        const r = await fetch(url, { headers: authHeaders });
        if (!r.ok) {
          // Read the body server-side ONLY to detect a resync signal; never surface it to the caller
          // (it can carry provider internals / mailbox identifiers, and this route is reachable by any
          // agento-net container).
          const errText = await r.text().catch(() => '');
          let code = '';
          try {
            code = ((JSON.parse(errText) || {}).error || {}).code || '';
          } catch {
            /* non-JSON body */
          }
          const needsResync = r.status === 410 || code === 'syncStateNotFound' || code === 'resyncRequired';
          if (needsResync && !resynced) {
            resynced = true;
            url = baseDeltaUrl(mailbox, top);
            raw.length = 0;
            continue;
          }
          log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId ?? '?'} delta failed (HTTP ${r.status}${code ? ' ' + code : ''})`);
          return res.status(needsResync ? 502 : r.status).json({ error: `Graph delta request failed (HTTP ${r.status})` });
        }
        const data = await r.json();
        for (const m of data.value || []) raw.push(m);
        if (data['@odata.nextLink']) {
          if (!isGraphUrl(data['@odata.nextLink'])) {
            // defense-in-depth: Graph only ever hands back graph URLs
            log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId ?? '?'} non-Graph nextLink`);
            return res.status(502).json({ error: 'Graph delta returned an unexpected nextLink' });
          }
          url = data['@odata.nextLink'];
          continue;
        }
        deltaLink = data['@odata.deltaLink'] || null;
        break;
      }
      // FAIL-CLOSED: never return a partial set as success. No deltaLink reached → didn't page to the end.
      if (!deltaLink) {
        log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId ?? '?'} delta did not reach a deltaLink`);
        return res.status(502).json({ error: 'Graph delta did not complete' });
      }

      // Map + (if needed) hydrate DMARC. internetMessageHeaders is required for the gate; if delta omitted
      // it for an item, fetch it per-message (a toolbox-built graph URL; bounded by new mail).
      const messages = [];
      for (const m of raw) {
        // Graph delta emits folder-sync events that are NOT live mail: moved/deleted items arrive as
        // { id, "@removed": {...} } (and read/unread flips re-emit a full message, handled below via
        // idempotency). Skip @removed — they carry no headers, so hydrating them would 404 → 502 →
        // pin the cursor forever. They are not published; the cursor still advances on the deltaLink.
        if (m['@removed']) continue;
        let headers = m.internetMessageHeaders;
        if (!Array.isArray(headers)) {
          const hr = await fetch(
            `${GRAPH_BASE}/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(m.id)}?$select=internetMessageHeaders`,
            { headers: authHeaders }
          );
          if (!hr.ok) {
            // FAIL-CLOSED: unverifiable DMARC must NOT advance the cursor — hold + retry
            await hr.text().catch(() => '');
            log('api/outlook/delta', 'ERROR', `agent_view_id=${agentViewId ?? '?'} header hydration failed (HTTP ${hr.status})`);
            return res.status(502).json({ error: 'Graph header hydration failed' });
          }
          headers = (await hr.json()).internetMessageHeaders;
        }
        messages.push({
          id: m.id,
          subject: m.subject,
          from: { name: m.from?.emailAddress?.name, address: m.from?.emailAddress?.address },
          receivedDateTime: m.receivedDateTime,
          conversationId: m.conversationId,
          dmarc: parseDmarcVerdict(headers),
        });
      }
      log('api/outlook/delta', 'OK', `agent_view_id=${agentViewId ?? '?'} ${messages.length} changed resynced=${resynced}`);
      return res.json({ mailbox, messages, deltaLink, resynced });
    } catch (err) {
      log('api/outlook/delta', 'ERROR', err.message); // server-side cron log only
      return res.status(500).json({ error: 'Internal error fetching delta mail' }); // sanitized to caller
    }
  };
}
