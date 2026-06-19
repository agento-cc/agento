import { z } from 'zod';
import { createGraphAuth } from './graph-auth.js';

const GRAPH_BASE = 'https://graph.microsoft.com/v1.0';

// Replicate core's matchesWhitelist semantics locally (src/agento/modules/core/toolbox/email.js) rather
// than importing it (avoids an inter-module dependency). Anchored, case-insensitive; the glob `*` ->
// `[^@]*` (matches a local part but never crosses `@`); every OTHER regex metachar in the literal
// segments is escaped (so `a?b@x.com` matches literally, never as a `?` quantifier — escaping the
// fail-OPEN direction). An EMPTY whitelist matches nothing -> blocks all (fail-closed). Kept in lockstep
// with channel.py `_matches_allowed`. Exported for direct unit testing.
export function matchesWhitelist(email, whitelist) {
  const addr = (email || '').toLowerCase();
  return whitelist.some((pattern) => {
    const re =
      '^' +
      pattern
        .toLowerCase()
        .split('*')
        .map((seg) => seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .join('[^@]*') +
      '$';
    return new RegExp(re).test(addr);
  });
}

function loadWhitelist(moduleConfigs) {
  return (moduleConfigs?.core?.email_whitelist || '')
    .split(',')
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean);
}

// Inbound allow-list (outlook/allowed_senders) — same comma-separated glob format used by the publisher
// gate (channel.py). Drives the read-tool restriction below.
function loadAllowedSenders(cfg) {
  return (cfg?.allowed_senders || '')
    .split(',')
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean);
}

// Config booleans arrive as a real bool (config.json) or a string (DB/ENV). Missing/empty -> default.
function parseBool(value, dflt) {
  if (value === undefined || value === null || value === '') return dflt;
  if (typeof value === 'boolean') return value;
  return ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase());
}

// On a non-ok Graph response, drain+discard the body (it can carry mailbox/tenant identifiers we must
// NOT surface to the agent — same policy as api-handlers.js) and throw a STATUS-ONLY error. The tool
// catch blocks log this server-side and return it to the agent already sanitized.
async function ensureOk(res) {
  if (!res.ok) {
    await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}`);
  }
}

// Accept only strict ISO-8601 datetimes before interpolating into an OData $filter (never raw-interpolate
// agent input). Returns true for e.g. 2026-01-02T03:04:05Z / +01:00 / with fractional seconds.
function isIso8601(value) {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(value);
}

const FOLDER_MAP = { inbox: 'Inbox', sentitems: 'SentItems', drafts: 'Drafts' };

export function register(server, { log, moduleConfigs, isToolEnabled, graphAuthFactory }) {
  const cfg = moduleConfigs?.outlook || {};
  const auth = (graphAuthFactory || createGraphAuth)(cfg);
  const whitelist = loadWhitelist(moduleConfigs);

  // S3 READ RESTRICTION: when `restrict_read_to_allowed_senders` is on (DEFAULT true), the read tools
  // (get_message / search / get_new) only surface mail whose sender is on outlook/allowed_senders —
  // mirroring the inbound publisher gate so an enabled read tool can't expose mail the channel would
  // never have created a job for (incl. spoofed / DMARC-failed mail sharing the mailbox). Empty
  // allowed_senders = block all (fail-closed). Disabling this is a documented security risk.
  const allowedSenders = loadAllowedSenders(cfg);
  const restrictRead = parseBool(cfg.restrict_read_to_allowed_senders, true);
  const senderAllowed = (addr) => !restrictRead || matchesWhitelist(addr || '', allowedSenders);

  // Per-tool opt-in gate. At startup (registerModuleRestApis) isToolEnabled is undefined and the server
  // is a no-op stub, so registering is harmless; at session time a disabled tool is skipped entirely.
  const enabled = (name) => !isToolEnabled || isToolEnabled(name);

  async function graphFetch(p, options = {}) {
    const token = await auth.getToken();
    return fetch(`${GRAPH_BASE}${p}`, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...options.headers },
    });
  }

  function notConfigured(toolName) {
    log(toolName, 'ERROR', 'Graph API not configured');
    return {
      content: [{ type: 'text', text: 'Error: Graph API not configured (set outlook_* config and a cert or client secret).' }],
      isError: true,
    };
  }

  // --- outlook_get_message ---
  if (enabled('outlook_get_message')) {
    server.tool(
      'outlook_get_message',
      [
        'Read a full email message from the Outlook mailbox by message ID.',
        'Returns: subject, from, to, cc, body (text), receivedDateTime, conversationId, hasAttachments.',
      ].join('\n'),
      { message_id: z.string().describe('Graph message ID') },
      async ({ message_id }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_get_message');
        const mailbox = auth.getMailboxUserId();
        try {
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}` +
              '?$select=subject,body,from,toRecipients,ccRecipients,receivedDateTime,conversationId,hasAttachments'
          );
          await ensureOk(res);
          const msg = await res.json();
          const result = {
            subject: msg.subject,
            from: { name: msg.from?.emailAddress?.name, address: msg.from?.emailAddress?.address },
            to: (msg.toRecipients || []).map((r) => ({ name: r.emailAddress?.name, address: r.emailAddress?.address })),
            cc: (msg.ccRecipients || []).map((r) => ({ name: r.emailAddress?.name, address: r.emailAddress?.address })),
            body: msg.body?.content,
            bodyType: msg.body?.contentType,
            receivedDateTime: msg.receivedDateTime,
            conversationId: msg.conversationId,
            hasAttachments: msg.hasAttachments,
          };
          if (!senderAllowed(result.from.address)) {
            log('outlook_get_message', 'BLOCKED', `mailbox=${mailbox} sender not in allowed_senders (read restricted)`);
            return {
              content: [{ type: 'text', text: 'Error: message sender is not in allowed_senders; reading is restricted (set outlook/restrict_read_to_allowed_senders=false to allow — security risk).' }],
              isError: true,
            };
          }
          log('outlook_get_message', 'OK', `mailbox=${mailbox} subject="${msg.subject}" from=${result.from.address}`);
          return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
        } catch (err) {
          log('outlook_get_message', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error reading message: ${err.message}` }], isError: true };
        }
      }
    );
  }

  // --- outlook_reply (recipient-gated: the original sender must be whitelisted) ---
  if (enabled('outlook_reply')) {
    server.tool(
      'outlook_reply',
      [
        'Reply to an email message. Creates a proper threaded reply (Re: subject, correct headers).',
        'The reply goes to the original sender, who must be in the email whitelist (core/email_whitelist).',
      ].join('\n'),
      {
        message_id: z.string().describe('Graph message ID to reply to'),
        body: z.string().describe('Reply body (plain text)'),
      },
      async ({ message_id, body }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_reply');
        const mailbox = auth.getMailboxUserId();
        try {
          // Require-route governs which JOBS are created; it does NOT constrain MCP calls. outlook_reply
          // sends external email, so gate the actual recipient (the message's sender) against the
          // whitelist — identical to outlook_send_mail / core email_send.
          const fromRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}?$select=from`
          );
          await ensureOk(fromRes);
          const senderAddr = (await fromRes.json())?.from?.emailAddress?.address || '';
          if (!matchesWhitelist(senderAddr, whitelist)) {
            log('outlook_reply', 'BLOCKED', `mailbox=${mailbox} recipient="${senderAddr}" not in whitelist`);
            return {
              content: [{ type: 'text', text: `Error: reply recipient "${senderAddr}" is not in the allowed recipients whitelist.` }],
              isError: true,
            };
          }
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/reply`,
            { method: 'POST', body: JSON.stringify({ comment: body }) }
          );
          await ensureOk(res);
          log('outlook_reply', 'OK', `mailbox=${mailbox} to=${senderAddr} message_id=${message_id.slice(0, 20)}...`);
          return { content: [{ type: 'text', text: 'Reply sent successfully.' }] };
        } catch (err) {
          log('outlook_reply', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error sending reply: ${err.message}` }], isError: true };
        }
      }
    );
  }

  // --- outlook_search_messages ---
  if (enabled('outlook_search_messages')) {
    server.tool(
      'outlook_search_messages',
      [
        'Search email messages with filters (subject, sender, date range, body text).',
        'Returns: message_id, subject, from, to[], receivedDateTime, isRead.',
      ].join('\n'),
      {
        folder: z.enum(['inbox', 'sentitems', 'drafts']).optional().default('inbox').describe('Mail folder to search'),
        subject_contains: z.string().optional().describe('Filter: subject contains this text'),
        from_contains: z.string().optional().describe('Filter: sender address contains this text'),
        to_contains: z.string().optional().describe('Filter: recipient address contains this text'),
        body_contains: z.string().optional().describe('Filter: body contains this text'),
        received_after: z.string().optional().describe('Filter: received after this ISO8601 datetime'),
        received_before: z.string().optional().describe('Filter: received before this ISO8601 datetime'),
        limit: z.number().optional().default(10).describe('Max messages to return (max 50)'),
      },
      async ({ folder, subject_contains, from_contains, to_contains, body_contains, received_after, received_before, limit }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_search_messages');
        const mailbox = auth.getMailboxUserId();
        const graphFolder = FOLDER_MAP[folder] || 'Inbox';

        const filters = [];
        const esc = (v) => v.replace(/'/g, "''");
        if (subject_contains) filters.push(`contains(subject, '${esc(subject_contains)}')`);
        if (from_contains) filters.push(`contains(from/emailAddress/address, '${esc(from_contains)}')`);
        if (to_contains) filters.push(`contains(toRecipients/emailAddress/address, '${esc(to_contains)}')`);
        if (body_contains) filters.push(`contains(body/content, '${esc(body_contains)}')`);
        if (received_after) {
          if (!isIso8601(received_after)) {
            return { content: [{ type: 'text', text: 'Error: received_after must be an ISO-8601 datetime (e.g. 2026-01-02T03:04:05Z).' }], isError: true };
          }
          filters.push(`receivedDateTime ge ${received_after}`);
        }
        if (received_before) {
          if (!isIso8601(received_before)) {
            return { content: [{ type: 'text', text: 'Error: received_before must be an ISO-8601 datetime (e.g. 2026-01-02T03:04:05Z).' }], isError: true };
          }
          filters.push(`receivedDateTime le ${received_before}`);
        }

        const filterParam = filters.length > 0 ? `&$filter=${encodeURIComponent(filters.join(' and '))}` : '';
        const top = Math.min(Math.max(Number.isFinite(limit) ? limit : 10, 1), 50);

        try {
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/mailFolders/${encodeURIComponent(graphFolder)}/messages` +
              `?$select=id,subject,from,toRecipients,receivedDateTime,isRead` +
              `&$orderby=receivedDateTime desc` +
              `&$top=${top}` +
              filterParam
          );
          await ensureOk(res);
          const data = await res.json();
          const messages = (data.value || [])
            .map((m) => ({
              message_id: m.id,
              subject: m.subject,
              from: m.from?.emailAddress?.address,
              to: (m.toRecipients || []).map((r) => r.emailAddress?.address),
              receivedDateTime: m.receivedDateTime,
              isRead: m.isRead,
            }))
            .filter((m) => senderAllowed(m.from)); // S3: hide non-allow-listed senders (from is the address string — stable contract)
          log('outlook_search_messages', 'OK', `mailbox=${mailbox} folder=${folder} ${messages.length} results`);
          return { content: [{ type: 'text', text: JSON.stringify(messages, null, 2) }] };
        } catch (err) {
          log('outlook_search_messages', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error searching messages: ${err.message}` }], isError: true };
        }
      }
    );
  }

  // --- outlook_get_new_messages ---
  if (enabled('outlook_get_new_messages')) {
    server.tool(
      'outlook_get_new_messages',
      [
        'List unread (new) email messages from the Inbox, sorted oldest first.',
        'Returns: message_id, subject, from, to[], receivedDateTime, isRead.',
      ].join('\n'),
      { limit: z.number().optional().default(10).describe('Max messages to return (max 50)') },
      async ({ limit }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_get_new_messages');
        const mailbox = auth.getMailboxUserId();
        const top = Math.min(Math.max(Number.isFinite(limit) ? limit : 10, 1), 50);
        try {
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/mailFolders/Inbox/messages` +
              `?$filter=isRead eq false` +
              `&$select=id,subject,from,toRecipients,receivedDateTime,isRead` +
              `&$orderby=receivedDateTime asc` +
              `&$top=${top}`
          );
          await ensureOk(res);
          const data = await res.json();
          const messages = (data.value || [])
            .map((m) => ({
              message_id: m.id,
              subject: m.subject,
              from: m.from?.emailAddress?.address,
              to: (m.toRecipients || []).map((r) => r.emailAddress?.address),
              receivedDateTime: m.receivedDateTime,
              isRead: m.isRead,
            }))
            .filter((m) => senderAllowed(m.from)); // S3: hide non-allow-listed senders (from is the address string — stable contract)
          log('outlook_get_new_messages', 'OK', `mailbox=${mailbox} ${messages.length} unread`);
          return { content: [{ type: 'text', text: JSON.stringify(messages, null, 2) }] };
        } catch (err) {
          log('outlook_get_new_messages', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error listing new messages: ${err.message}` }], isError: true };
        }
      }
    );
  }

  // --- outlook_send_mail (recipient-gated) ---
  if (enabled('outlook_send_mail')) {
    server.tool(
      'outlook_send_mail',
      [
        'Send a new email message (not a reply), sent from the agent mailbox.',
        'All recipients (to, cc) must be in the email whitelist (core/email_whitelist).',
      ].join('\n'),
      {
        to: z.array(z.string().email()).describe('Recipient email addresses'),
        subject: z.string().describe('Email subject'),
        body: z.string().describe('Email body (plain text)'),
        cc: z.array(z.string().email()).optional().describe('CC recipient email addresses'),
      },
      async ({ to, subject, body, cc }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_send_mail');
        const allRecipients = [...to, ...(cc || [])];
        const blocked = allRecipients.filter((addr) => !matchesWhitelist(addr, whitelist));
        if (blocked.length > 0) {
          log('outlook_send_mail', 'BLOCKED', `blocked=${blocked.join(',')}`);
          return { content: [{ type: 'text', text: `Error: Recipients not in whitelist: ${blocked.join(', ')}` }], isError: true };
        }
        const mailbox = auth.getMailboxUserId();
        const toRecipients = to.map((addr) => ({ emailAddress: { address: addr } }));
        const ccRecipients = (cc || []).map((addr) => ({ emailAddress: { address: addr } }));
        try {
          const res = await graphFetch(`/users/${encodeURIComponent(mailbox)}/sendMail`, {
            method: 'POST',
            body: JSON.stringify({
              message: {
                subject,
                body: { contentType: 'Text', content: body },
                toRecipients,
                ...(ccRecipients.length > 0 && { ccRecipients }),
              },
            }),
          });
          await ensureOk(res);
          log('outlook_send_mail', 'OK', `mailbox=${mailbox} to=${to.join(',')} subject="${subject}"`);
          return { content: [{ type: 'text', text: 'Email sent successfully.' }] };
        } catch (err) {
          log('outlook_send_mail', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error sending email: ${err.message}` }], isError: true };
        }
      }
    );
  }

  // --- outlook_mark_processed ---
  if (enabled('outlook_mark_processed')) {
    server.tool(
      'outlook_mark_processed',
      ['Mark an email message as read (processed).', 'Use after finishing an email task.'].join('\n'),
      { message_id: z.string().describe('Graph message ID to mark as read') },
      async ({ message_id }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_mark_processed');
        const mailbox = auth.getMailboxUserId();
        try {
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}`,
            { method: 'PATCH', body: JSON.stringify({ isRead: true }) }
          );
          await ensureOk(res);
          log('outlook_mark_processed', 'OK', `mailbox=${mailbox} message_id=${message_id.slice(0, 20)}...`);
          return { content: [{ type: 'text', text: 'Message marked as read.' }] };
        } catch (err) {
          log('outlook_mark_processed', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error marking message as read: ${err.message}` }], isError: true };
        }
      }
    );
  }
}
