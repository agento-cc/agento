import { z } from 'zod';
import { stat, lstat, realpath, readFile, writeFile, mkdir } from 'node:fs/promises';
import { basename, join, resolve, sep } from 'node:path';
import { createGraphAuth } from './graph-auth.js';
import { parseDmarcVerdict } from './api-handlers.js';

const GRAPH_BASE = 'https://graph.microsoft.com/v1.0';

const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
const SIMPLE_ATTACH_LIMIT = 3 * 1024 * 1024; // <3 MB → simple POST; ≥3 MB → upload session
const UPLOAD_CHUNK = 320 * 1024 * 10; // 3.2 MB, a 320 KB multiple, <4 MB (Graph upload requirement)

// Resolve `p` to its REAL path (following `..` and symlinks) and assert it stays inside /workspace/.
// This code runs in the toolbox (the secrets container), so a path that escapes /workspace lets the
// untrusted agent make the toolbox read a host/secret file and email it out — a prefix-only
// startsWith('/workspace/') check is INSUFFICIENT (/workspace/../etc/passwd passes it, and a symlink
// under /workspace can point outside). Resolving the real path closes both. Re-resolving /workspace per
// call is negligible (≤10 files). Throws (never returns) when the path is missing or escapes — callers
// turn that into an isError before any Graph call. Shared by validateAttachments (file paths), the
// download write (artifactsDir), and the read-time re-check in attachAndSendDraft.
async function realpathWithin(p) {
  const wsReal = await realpath('/workspace');
  const real = await realpath(p);
  if (real !== wsReal && !real.startsWith(wsReal + sep)) {
    throw new Error(`path "${p}" escapes /workspace`);
  }
  return real;
}

// Create `dir` (which must be /workspace or under it) WITHOUT ever following a symlink. mkdir's
// `recursive: true` follows an existing intermediate symlink, so if the agent pre-creates a component
// such as /workspace/artifacts as a symlink to outside, a plain recursive mkdir would create directories
// OUTSIDE /workspace before any containment check runs. Anchor on realpath('/workspace') and create each
// missing segment one at a time, rejecting any existing segment that is a symlink or non-directory
// (lstat) — so no symlink is traversed and nothing is created outside the real workspace. Returns the
// resolved, contained directory. Throws on escape/symlink; callers turn that into an isError (no write).
async function mkdirWithinWorkspace(dir) {
  const wsReal = await realpath('/workspace');
  if (dir !== '/workspace' && !dir.startsWith('/workspace/')) {
    throw new Error(`path "${dir}" escapes /workspace`);
  }
  const rel = dir === '/workspace' ? '' : dir.slice('/workspace/'.length);
  let current = wsReal;
  for (const seg of rel.split('/').filter(Boolean)) {
    const next = join(current, seg);
    let info = null;
    try {
      info = await lstat(next);
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    if (info) {
      if (info.isSymbolicLink() || !info.isDirectory()) {
        throw new Error(`path component "${next}" is not a real directory`);
      }
    } else {
      try {
        await mkdir(next); // non-recursive: parent is a verified real dir, so this cannot follow a symlink
      } catch (err) {
        if (err.code !== 'EEXIST') throw err;
        // Lost a benign race with a concurrent worker creating the same dir — re-check it is a real dir.
        const raced = await lstat(next);
        if (raced.isSymbolicLink() || !raced.isDirectory()) {
          throw new Error(`path component "${next}" is not a real directory`);
        }
      }
    }
    current = next;
  }
  return current;
}

// Validate agent-supplied attachment paths BEFORE any Graph call. Hardened replica of core/email.js's
// validateAttachments (NOT imported — inter-module dependency, like matchesWhitelist): adds realpath
// traversal/symlink containment because this runs in the secrets container. Returns { error, records }
// with records = [{ realPath, name, size }]; realPath is the resolved, contained path used for ALL later
// I/O so the validated path is exactly the read path. First failing path → { error, records: [] }.
async function validateAttachments(paths) {
  const records = [];
  for (const p of paths) {
    if (!p.startsWith('/workspace/')) {
      return { error: `Error: attachment path "${p}" must be inside /workspace/`, records: [] };
    }
    let real;
    try {
      real = await realpathWithin(p);
    } catch (err) {
      // Not-found (realpath throws ENOENT) and escape both land here — never reveal which.
      if (err.message && err.message.includes('escapes /workspace')) {
        return { error: `Error: attachment path "${p}" escapes /workspace`, records: [] };
      }
      return { error: `Error: attachment "${p}" not found (${err.code || err.message})`, records: [] };
    }
    let info;
    try {
      info = await stat(real);
    } catch (err) {
      return { error: `Error: attachment "${p}" not found (${err.code || err.message})`, records: [] };
    }
    if (!info.isFile()) {
      return { error: `Error: attachment "${p}" is not a regular file`, records: [] };
    }
    if (info.size > MAX_ATTACHMENT_BYTES) {
      return { error: `Error: attachment "${p}" is ${info.size} bytes; exceeds 25 MB cap`, records: [] };
    }
    records.push({ realPath: real, name: basename(p), size: info.size });
  }
  return { error: null, records };
}

// Host guard for Graph upload-session URLs (AC4). The chunked PUT carries the raw attachment bytes with
// NO Authorization header (the session URL is the capability), so a Graph-returned URL pointing at a
// foreign host would exfiltrate bytes. Accept ONLY https + outlook.office.com (or a subdomain) with no
// embedded credentials. Any parse error ⇒ false (fail-closed). Exported for direct unit testing.
export function isOutlookUploadUrl(u) {
  try {
    const url = new URL(u);
    return (
      url.protocol === 'https:' &&
      (url.hostname === 'outlook.office.com' || url.hostname.endsWith('.outlook.office.com')) &&
      url.username === '' &&
      url.password === ''
    );
  } catch {
    return false;
  }
}

// Map a Graph attachment @odata.type to a short kind. Default 'file'.
function odataAttachmentType(t) {
  if (t === '#microsoft.graph.itemAttachment') return 'item';
  if (t === '#microsoft.graph.referenceAttachment') return 'reference';
  return 'file';
}

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

export function register(server, { log, moduleConfigs, isToolEnabled, graphAuthFactory, artifactsDir }) {
  const cfg = moduleConfigs?.outlook || {};
  const auth = (graphAuthFactory || createGraphAuth)(cfg);
  const whitelist = loadWhitelist(moduleConfigs);

  // S3 READ RESTRICTION: when `restrict_read_to_allowed_senders` is on (DEFAULT true), the read tools
  // (get_message / search / get_new) surface a message only if it passes the SAME gate as the inbound
  // publisher (channel.py): sender on outlook/allowed_senders AND a DMARC `pass`. The From header is
  // forgeable, so an allow-listed sender alone is NOT enough — DMARC is the cryptographic proof; without
  // it a spoofed allow-listed From on a DMARC-failing mail would be readable (a prompt-injection vector).
  // The verdict is the immutable receipt-time Authentication-Results header (parseDmarcVerdict), checked
  // FAIL-CLOSED: no verifiable `pass` ⇒ not surfaced. Empty allowed_senders = block all. Disabling
  // restrict_read_to_allowed_senders bypasses BOTH checks (lets the agent read any mail) — a documented
  // security risk. `surfaceAllowed` is the sync gate for a SINGLE-message GET (which reliably returns the
  // selected internetMessageHeaders); list tools use the async `readGatePass` below (collections don't).
  const allowedSenders = loadAllowedSenders(cfg);
  const restrictRead = parseBool(cfg.restrict_read_to_allowed_senders, true);
  const surfaceAllowed = (addr, headers) =>
    !restrictRead || (matchesWhitelist(addr || '', allowedSenders) && parseDmarcVerdict(headers) === 'pass');

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

  // Attach validated files to an already-created draft (createReply OR POST /messages) and send it.
  // Defined INSIDE register() so it closes over the session-scoped graphFetch (like graphFetch /
  // surfaceAllowed / notConfigured) — never a module-level function reading per-session auth from module
  // scope (that is the cross-session contamination pattern the rules forbid). Shared by outlook_reply and
  // outlook_send_mail; the only per-tool difference is who created the draft. On ANY failure after the
  // draft exists, best-effort DELETE the draft (no orphan) then re-throw to the caller's outer catch.
  async function attachAndSendDraft(mailbox, draftId, records) {
    try {
      for (const { realPath, name } of records) {
        // Re-validate at read time (close the TOCTOU between early validation and upload): re-resolve +
        // re-assert /workspace containment (catches a post-validation symlink/file swap; throws → cleanup
        // runs), read from the FRESH resolved path, and use the ACTUAL byte length (not the stale
        // validated size) for the branch decision and the Graph size/Content-Range.
        const fresh = await realpathWithin(realPath);
        const bytes = await readFile(fresh);
        if (bytes.length > MAX_ATTACHMENT_BYTES) {
          throw new Error(`attachment "${name}" is ${bytes.length} bytes; exceeds 25 MB cap`);
        }
        if (bytes.length < SIMPLE_ATTACH_LIMIT) {
          // <3 MB → simple POST. (createUploadSession REJECTS files <3 MB with
          // ErrorAttachmentSizeShouldNotBeLessThanMinimumSize, so this branch is mandatory.)
          const ar = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(draftId)}/attachments`,
            {
              method: 'POST',
              body: JSON.stringify({
                '@odata.type': '#microsoft.graph.fileAttachment',
                name,
                contentBytes: bytes.toString('base64'),
              }),
            }
          );
          await ensureOk(ar);
        } else {
          // ≥3 MB → upload session + chunked PUT.
          const sr = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(draftId)}/attachments/createUploadSession`,
            {
              method: 'POST',
              body: JSON.stringify({ AttachmentItem: { attachmentType: 'file', name, size: bytes.length } }),
            }
          );
          await ensureOk(sr);
          const uploadUrl = (await sr.json())?.uploadUrl;
          if (!isOutlookUploadUrl(uploadUrl)) throw new Error('untrusted upload URL');
          for (let start = 0; start < bytes.length; start += UPLOAD_CHUNK) {
            const end = Math.min(start + UPLOAD_CHUNK, bytes.length) - 1;
            const chunk = bytes.subarray(start, end + 1);
            // RAW fetch (not graphFetch) so it carries NO Authorization header (the session URL is the
            // capability), its own Content-Range, and Content-Type: application/octet-stream (required by
            // Graph on upload PUTs). redirect:'manual' so native fetch can't follow a 3xx that would
            // forward raw bytes to a host the guard never checked; ensureOk then rejects the opaque
            // redirect / non-2xx.
            const pr = await fetch(uploadUrl, {
              method: 'PUT',
              redirect: 'manual',
              headers: {
                'Content-Length': String(chunk.length),
                'Content-Range': `bytes ${start}-${end}/${bytes.length}`,
                'Content-Type': 'application/octet-stream',
              },
              body: chunk,
            });
            await ensureOk(pr);
          }
        }
      }
      // Send returns 202 Accepted; ensureOk's res.ok covers all 2xx. Graph auto-saves to Sent Items.
      const sendRes = await graphFetch(
        `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(draftId)}/send`,
        { method: 'POST' }
      );
      await ensureOk(sendRes);
    } catch (err) {
      // Best-effort cleanup so a half-built draft never lingers in Drafts; swallow its own error.
      try {
        await graphFetch(
          `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(draftId)}`,
          { method: 'DELETE' }
        );
      } catch {
        /* ignore cleanup failure */
      }
      throw err;
    }
  }

  // Async read gate for LIST results: a Graph message COLLECTION does not reliably return
  // internetMessageHeaders even when $select-ed (unlike a single-message GET), so when a listed item
  // omits them we hydrate the verdict via a per-message GET — bounded to an already-allow-listed sender
  // (so junk is never hydrated) and FAIL-CLOSED (any hydration failure / unverifiable verdict ⇒ dropped).
  // Mirrors the publisher's delta-handler hydration. Returns true iff the message is surfaceable.
  async function readGatePass(m) {
    if (!restrictRead) return true;
    const addr = m.from?.emailAddress?.address;
    if (!matchesWhitelist(addr || '', allowedSenders)) return false;
    let headers = m.internetMessageHeaders;
    if (!Array.isArray(headers)) {
      try {
        const hr = await graphFetch(
          `/users/${encodeURIComponent(auth.getMailboxUserId())}/messages/${encodeURIComponent(m.id)}?$select=internetMessageHeaders`
        );
        if (!hr.ok) {
          await hr.text().catch(() => ''); // drain+discard (never surface a Graph body)
          return false;
        }
        headers = (await hr.json()).internetMessageHeaders;
      } catch {
        return false;
      }
    }
    return parseDmarcVerdict(headers) === 'pass';
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
        'Returns: subject, from, to, cc, body (text), receivedDateTime, conversationId, hasAttachments,',
        'attachments[] (metadata: attachment_id, name, contentType, size, isInline, type) — use',
        'outlook_get_attachment to download a file.',
      ].join('\n'),
      { message_id: z.string().describe('Graph message ID') },
      async ({ message_id }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_get_message');
        const mailbox = auth.getMailboxUserId();
        try {
          const res = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}` +
              '?$select=subject,body,from,toRecipients,ccRecipients,receivedDateTime,conversationId,hasAttachments,internetMessageHeaders'
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
          // Gate stays FIRST: a blocked message lists nothing (no attachment fetch happens).
          if (!surfaceAllowed(result.from.address, msg.internetMessageHeaders)) {
            log('outlook_get_message', 'BLOCKED', `mailbox=${mailbox} sender not allow-listed or DMARC not pass (read restricted)`);
            return {
              content: [{ type: 'text', text: 'Error: message sender is not in allowed_senders or did not pass DMARC; reading is restricted (set outlook/restrict_read_to_allowed_senders=false to allow — security risk).' }],
              isError: true,
            };
          }
          // After the gate passes, fetch attachment METADATA only ($select excludes contentBytes, so no
          // bytes are pulled). Own try/catch: a transient metadata error must NOT hide an already-gated-OK
          // body. @odata.type is a control annotation (not always $select-able) — Graph returns it by
          // default on every polymorphic attachment, so read it from the response.
          if (msg.hasAttachments) {
            try {
              const ar = await graphFetch(
                `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/attachments` +
                  '?$select=id,name,contentType,size,isInline'
              );
              await ensureOk(ar);
              const data = await ar.json();
              result.attachments = (data.value || []).map((a) => ({
                attachment_id: a.id,
                name: a.name,
                contentType: a.contentType,
                size: a.size,
                isInline: a.isInline,
                type: odataAttachmentType(a['@odata.type']),
              }));
            } catch (err) {
              log('outlook_get_message', 'WARN', `mailbox=${mailbox} attachment metadata fetch failed: ${err.message}`);
              result.attachments = [];
            }
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

  // --- outlook_get_attachment (download ONE attachment to the artifacts dir; opt-in) ---
  if (enabled('outlook_get_attachment')) {
    server.tool(
      'outlook_get_attachment',
      [
        'Download one file attachment from an email to the job artifacts directory.',
        'Re-applies the SAME read-gate as the read tools (sender allow-listed + DMARC pass) before any',
        'download, rejects non-file attachments and anything over 25 MB, and returns { path, name,',
        'contentType, size }. The saved path can then be attached to a reply or a new email.',
      ].join('\n'),
      {
        message_id: z.string().describe('Graph message ID the attachment belongs to'),
        attachment_id: z.string().describe('Attachment ID from outlook_get_message attachments[]'),
      },
      async ({ message_id, attachment_id }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_get_attachment');
        const mailbox = auth.getMailboxUserId();
        try {
          // 1. Re-apply the read gate BEFORE any download. Same message GET shape the read tools use
          //    (from + internetMessageHeaders). Blocked ⇒ isError, NO $value GET issued.
          const gateRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}?$select=from,internetMessageHeaders`
          );
          await ensureOk(gateRes);
          const gateMsg = await gateRes.json();
          if (!surfaceAllowed(gateMsg.from?.emailAddress?.address, gateMsg.internetMessageHeaders)) {
            log('outlook_get_attachment', 'BLOCKED', `mailbox=${mailbox} sender not allow-listed or DMARC not pass (read restricted)`);
            return {
              content: [{ type: 'text', text: 'Error: message sender is not in allowed_senders or did not pass DMARC; downloading is restricted (set outlook/restrict_read_to_allowed_senders=false to allow — security risk).' }],
              isError: true,
            };
          }

          // 2. Metadata + type/size guard. Read @odata.type from the RESPONSE (not $select). Fail closed:
          //    only #microsoft.graph.fileAttachment may be downloaded.
          const metaRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/attachments/${encodeURIComponent(attachment_id)}?$select=id,name,contentType,size`
          );
          await ensureOk(metaRes);
          const meta = await metaRes.json();
          if (meta['@odata.type'] !== '#microsoft.graph.fileAttachment') {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} non-file attachment type=${meta['@odata.type']}`);
            return { content: [{ type: 'text', text: 'Error: only file attachments can be downloaded (item/reference attachments are not supported).' }], isError: true };
          }
          if (typeof meta.size === 'number' && meta.size > MAX_ATTACHMENT_BYTES) {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} attachment ${meta.size} bytes exceeds 25 MB`);
            return { content: [{ type: 'text', text: `Error: attachment is ${meta.size} bytes; exceeds the 25 MB cap.` }], isError: true };
          }

          // 3. Download raw bytes. Reject early if the response advertises a too-large Content-Length.
          const valRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/attachments/${encodeURIComponent(attachment_id)}/$value`
          );
          await ensureOk(valRes);
          const declaredLen = Number(valRes.headers?.get?.('Content-Length'));
          if (Number.isFinite(declaredLen) && declaredLen > MAX_ATTACHMENT_BYTES) {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} Content-Length ${declaredLen} exceeds 25 MB`);
            return { content: [{ type: 'text', text: `Error: attachment is ${declaredLen} bytes; exceeds the 25 MB cap.` }], isError: true };
          }
          const bytes = Buffer.from(await valRes.arrayBuffer());

          // 4. Enforce the REAL cap on the actual bytes (metadata can lie), then write symlink-safely.
          if (bytes.length > MAX_ATTACHMENT_BYTES) {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} downloaded ${bytes.length} bytes exceeds 25 MB`);
            return { content: [{ type: 'text', text: `Error: attachment is ${bytes.length} bytes; exceeds the 25 MB cap.` }], isError: true };
          }
          let safeName = basename(meta.name || 'attachment');
          if (!safeName || safeName === '.' || safeName === '..') safeName = 'attachment';

          // /workspace contents are agent-writable, so the agent could pre-create the artifacts path (or
          // an intermediate component) as a symlink pointing outside /workspace. Create the dir
          // symlink-safely (never following a symlink, never creating outside the real workspace) and use
          // the resolved, contained path it returns; throws → isError, no write.
          let artifactsReal;
          try {
            artifactsReal = await mkdirWithinWorkspace(artifactsDir);
          } catch (err) {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} artifacts dir escapes /workspace: ${err.message}`);
            return { content: [{ type: 'text', text: 'Error: could not write the attachment (artifacts directory is not inside /workspace).' }], isError: true };
          }
          let outPath = join(artifactsReal, safeName);
          // belt-and-suspenders lexical check (the realpath containment above is the real guard).
          if (!resolve(outPath).startsWith(artifactsReal + sep)) {
            log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} attachment name escapes artifacts dir`);
            return { content: [{ type: 'text', text: 'Error: attachment name is not allowed.' }], isError: true };
          }

          // No silent overwrite, race-free: exclusive-create (wx); on EEXIST bump a numeric suffix before
          // the extension and retry, so "no overwrite" is enforced by the filesystem, not a check gap.
          let written = false;
          let attempt = 0;
          while (!written) {
            try {
              await writeFile(outPath, bytes, { flag: 'wx' });
              written = true;
            } catch (err) {
              if (err.code !== 'EEXIST') throw err;
              attempt += 1;
              const dot = safeName.lastIndexOf('.');
              const stem = dot > 0 ? safeName.slice(0, dot) : safeName;
              const ext = dot > 0 ? safeName.slice(dot) : '';
              outPath = join(artifactsReal, `${stem}-${attempt}${ext}`);
            }
          }

          log('outlook_get_attachment', 'OK', `mailbox=${mailbox} wrote ${basename(outPath)} (${bytes.length} bytes)`);
          return {
            content: [
              {
                type: 'text',
                text: JSON.stringify(
                  { path: outPath, name: basename(outPath), contentType: meta.contentType, size: bytes.length },
                  null,
                  2
                ),
              },
            ],
          };
        } catch (err) {
          log('outlook_get_attachment', 'ERROR', `mailbox=${mailbox} ${err.message}`);
          return { content: [{ type: 'text', text: `Error downloading attachment: ${err.message}` }], isError: true };
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
        'The body must be valid HTML (e.g. <p>, <ul>/<li>, <b>) — it is sent as an HTML message body.',
        'Optional attachments: absolute file paths inside /workspace/ (e.g. files downloaded via',
        'outlook_get_attachment). Max 10 files; each up to 25 MB.',
      ].join('\n'),
      {
        message_id: z.string().describe('Graph message ID to reply to'),
        body: z.string().describe('Reply body as HTML markup (use <p>, <ul>/<li>, <b>; not plain text or markdown)'),
        attachments: z
          .array(z.string())
          .max(10)
          .optional()
          .describe('Absolute file paths inside /workspace/. Max 10 files; each up to 25 MB.'),
      },
      async ({ message_id, body, attachments }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_reply');
        const mailbox = auth.getMailboxUserId();
        try {
          // With attachments: validate FIRST so bad input returns isError before ANY Graph call.
          let records = [];
          if (attachments?.length) {
            const v = await validateAttachments(attachments);
            if (v.error) {
              log('outlook_reply', 'ERROR', `mailbox=${mailbox} ${v.error}`);
              return { content: [{ type: 'text', text: v.error }], isError: true };
            }
            records = v.records;
          }

          // Require-route governs which JOBS are created; it does NOT constrain MCP calls. outlook_reply
          // sends external email, so gate the actual recipient against the whitelist. Graph's /reply and
          // createReply deliver to the original message's Reply-To when present, else From — so gate the
          // address Graph actually delivers to (fetch from+replyTo): an allow-listed From with a hostile
          // Reply-To must not exfiltrate the reply to a non-whitelisted address.
          const fromRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}?$select=from,replyTo`
          );
          await ensureOk(fromRes);
          const meta = await fromRes.json();
          const replyToAddrs = (meta?.replyTo || []).map((r) => r.emailAddress?.address).filter(Boolean);
          const recipients = replyToAddrs.length
            ? replyToAddrs
            : [meta?.from?.emailAddress?.address || ''];
          const blocked = recipients.filter((addr) => !matchesWhitelist(addr, whitelist));
          if (blocked.length > 0) {
            log('outlook_reply', 'BLOCKED', `mailbox=${mailbox} recipient(s)="${blocked.join(',')}" not in whitelist`);
            return {
              content: [{ type: 'text', text: `Error: reply recipient "${blocked.join(', ')}" is not in the allowed recipients whitelist.` }],
              isError: true,
            };
          }

          // No-attachments path: byte-for-byte the existing single /reply POST. Send an HTML reply via the
          // /reply action's `message.body` (ItemBody, contentType HTML) — NOT the `comment` parameter,
          // which Graph treats as plain text only (mutually exclusive; both = HTTP 400). The /reply action
          // still threads the reply (Re: subject, In-Reply-To/References, conversationId).
          if (!records.length) {
            const res = await graphFetch(
              `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/reply`,
              { method: 'POST', body: JSON.stringify({ message: { body: { contentType: 'HTML', content: body } } }) }
            );
            await ensureOk(res);
            log('outlook_reply', 'OK', `mailbox=${mailbox} to=${recipients.join(',')} message_id=${message_id.slice(0, 20)}...`);
            return { content: [{ type: 'text', text: 'Reply sent successfully.' }] };
          }

          // With-attachments path: createReply (draft) → shared attach/send/cleanup helper.
          const draftRes = await graphFetch(
            `/users/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(message_id)}/createReply`,
            { method: 'POST', body: JSON.stringify({ message: { body: { contentType: 'HTML', content: body } } }) }
          );
          await ensureOk(draftRes);
          const draftId = (await draftRes.json())?.id;
          await attachAndSendDraft(mailbox, draftId, records);
          log('outlook_reply', 'OK', `mailbox=${mailbox} to=${recipients.join(',')} attachments=${records.length} message_id=${message_id.slice(0, 20)}...`);
          return { content: [{ type: 'text', text: `Reply sent successfully (${records.length} attachment${records.length === 1 ? '' : 's'}).` }] };
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
              `?$select=id,subject,from,toRecipients,receivedDateTime,isRead,internetMessageHeaders` +
              `&$orderby=receivedDateTime desc` +
              `&$top=${top}` +
              filterParam
          );
          await ensureOk(res);
          const data = await res.json();
          // S3: gate on the RAW message (sender + DMARC, hydrating headers if the collection omitted
          // them) BEFORE mapping, so headers never leak and a spoofed / DMARC-failed item is never surfaced.
          const messages = [];
          for (const m of data.value || []) {
            if (!(await readGatePass(m))) continue;
            messages.push({
              message_id: m.id,
              subject: m.subject,
              from: m.from?.emailAddress?.address,
              to: (m.toRecipients || []).map((r) => r.emailAddress?.address),
              receivedDateTime: m.receivedDateTime,
              isRead: m.isRead,
            });
          }
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
              `&$select=id,subject,from,toRecipients,receivedDateTime,isRead,internetMessageHeaders` +
              `&$orderby=receivedDateTime asc` +
              `&$top=${top}`
          );
          await ensureOk(res);
          const data = await res.json();
          // S3: gate on the RAW message (sender + DMARC, hydrating headers if the collection omitted
          // them) BEFORE mapping, so headers never leak and a spoofed / DMARC-failed item is never surfaced.
          const messages = [];
          for (const m of data.value || []) {
            if (!(await readGatePass(m))) continue;
            messages.push({
              message_id: m.id,
              subject: m.subject,
              from: m.from?.emailAddress?.address,
              to: (m.toRecipients || []).map((r) => r.emailAddress?.address),
              receivedDateTime: m.receivedDateTime,
              isRead: m.isRead,
            });
          }
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
        "Send a new email from the agent's Outlook mailbox. PREFERRED over the SMTP `email_send` when",
        "available — it sends from the agent's real mailbox via Microsoft Graph (correct sender identity,",
        'DMARC/SPF alignment) and supports attachments.',
        'All recipients (to, cc, bcc) must be in the email whitelist (core/email_whitelist).',
        'The body must be valid HTML (e.g. <p>, <ul>/<li>, <b>) — it is sent as an HTML message body.',
        'Optional attachments: absolute file paths inside /workspace/. Max 10 files; each up to 25 MB.',
      ].join('\n'),
      {
        to: z.array(z.string().email()).describe('Recipient email addresses'),
        subject: z.string().describe('Email subject'),
        body: z.string().describe('Email body as HTML markup (use <p>, <ul>/<li>, <b>; not plain text or markdown)'),
        cc: z.array(z.string().email()).optional().describe('CC recipient email addresses'),
        bcc: z.array(z.string().email()).optional().describe('Blind carbon-copy recipients. All must be in the whitelist.'),
        attachments: z
          .array(z.string())
          .max(10)
          .optional()
          .describe('Absolute file paths inside /workspace/. Max 10 files; each up to 25 MB.'),
      },
      async ({ to, subject, body, cc, bcc, attachments }) => {
        if (!auth.isConfigured()) return notConfigured('outlook_send_mail');
        // Recipient gate is the file-exfiltration choke point and runs FIRST (covers To+Cc+Bcc; Bcc is a
        // real, invisible recipient). Blocked ⇒ isError, no Graph call.
        const allRecipients = [...to, ...(cc || []), ...(bcc || [])];
        const blocked = allRecipients.filter((addr) => !matchesWhitelist(addr, whitelist));
        if (blocked.length > 0) {
          log('outlook_send_mail', 'BLOCKED', `blocked=${blocked.join(',')}`);
          return { content: [{ type: 'text', text: `Error: Recipients not in whitelist: ${blocked.join(', ')}` }], isError: true };
        }
        const mailbox = auth.getMailboxUserId();
        const toRecipients = to.map((addr) => ({ emailAddress: { address: addr } }));
        const ccRecipients = (cc || []).map((addr) => ({ emailAddress: { address: addr } }));
        const bccRecipients = (bcc || []).map((addr) => ({ emailAddress: { address: addr } }));
        try {
          // With attachments: validate FIRST (isError before ANY Graph call), then draft → shared helper.
          if (attachments?.length) {
            const v = await validateAttachments(attachments);
            if (v.error) {
              log('outlook_send_mail', 'ERROR', `mailbox=${mailbox} ${v.error}`);
              return { content: [{ type: 'text', text: v.error }], isError: true };
            }
            // Unified draft path (never inline /sendMail attachments — Graph caps the whole inline payload
            // at 4 MB). POST /messages creates a draft in Drafts; the shared helper attaches → sends →
            // DELETEs on failure (same machinery as reply; the draft-create is the only new Graph call).
            const draftRes = await graphFetch(`/users/${encodeURIComponent(mailbox)}/messages`, {
              method: 'POST',
              body: JSON.stringify({
                subject,
                body: { contentType: 'HTML', content: body },
                toRecipients,
                ...(ccRecipients.length > 0 && { ccRecipients }),
                ...(bccRecipients.length > 0 && { bccRecipients }),
              }),
            });
            await ensureOk(draftRes);
            const draftId = (await draftRes.json())?.id;
            await attachAndSendDraft(mailbox, draftId, v.records);
            log('outlook_send_mail', 'OK', `mailbox=${mailbox} to=${to.join(',')} attachments=${v.records.length} subject="${subject}"`);
            return { content: [{ type: 'text', text: `Email sent successfully (${v.records.length} attachment${v.records.length === 1 ? '' : 's'}).` }] };
          }

          // No-attachments path: byte-for-byte the existing single /sendMail POST (now also carrying
          // bccRecipients when present, mirroring ccRecipients).
          const res = await graphFetch(`/users/${encodeURIComponent(mailbox)}/sendMail`, {
            method: 'POST',
            body: JSON.stringify({
              message: {
                subject,
                body: { contentType: 'HTML', content: body },
                toRecipients,
                ...(ccRecipients.length > 0 && { ccRecipients }),
                ...(bccRecipients.length > 0 && { bccRecipients }),
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
