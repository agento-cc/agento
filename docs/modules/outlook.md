# Outlook Email Channel

Poll a Microsoft 365 mailbox for unread email and turn each authorized message into a job; the agent
reads, replies, and marks messages processed through MCP tools. Like every Agento channel, all
Microsoft Graph secrets and HTTP live in the **Node.js toolbox** (the zero-trust boundary); the Python
module provides the channel, publisher, polling command, onboarding, and manifests.

> **Security model in one line:** an inbound email creates a job **only** if its `From` is on the
> `outlook/allowed_senders` allow-list **and** the message passes DMARC. A whitelisted sender that fails
> DMARC is treated as a spoof — no job, and a `SECURITY_BREACH` is logged.

## Architecture

| Concern | Where |
|---|---|
| Graph auth (cert **or** client secret) | `toolbox/graph-auth.js` (`@azure/identity`) |
| 6 MCP tools (read / reply / search / list / send / mark) | `toolbox/outlook.js` |
| Unread-poll REST endpoint (`POST /api/outlook/unread`) + DMARC parse | `toolbox/api.js`, `toolbox/api-handlers.js` |
| Channel prompt fragments + publisher security gate | `src/channel.py` |
| Poll command (`outlook:publish`, cron every minute) | `src/commands/publish.py`, `cron.json` |
| Typed config (no secrets) | `src/config.py` (`OutlookConfig`) |
| Onboarding | `src/onboarding.py` |

## Configuration

Set via `agento config:set outlook/<key> <value>` (or `CONFIG__OUTLOOK__<KEY>` env). Keys:

| Key | Type | Notes |
|---|---|---|
| `outlook/enabled` | bool | Master switch for the channel (default `false`). |
| `outlook/outlook_tenant_id` | string | Azure AD tenant ID. |
| `outlook/outlook_client_id` | string | Azure app (client) ID. |
| `outlook/outlook_client_secret` | **obscure** | Client secret (encrypted at rest). Use **either** this **or** a cert. |
| `outlook/outlook_cert_path` | string | Path to a mounted PEM. Takes precedence over the secret when both are set. |
| `outlook/outlook_mailbox_user_id` | string | Mailbox UPN to poll, e.g. `agenty@kazar.com`. |
| `outlook/allowed_senders` | string | **Comma-separated allow-list** of `From` addresses/patterns. **Empty = block all.** |
| `outlook/require_dmarc` | bool | Require a DMARC pass for allow-listed senders (default `true`). |
| `outlook/poll_top` | int | Max unread fetched per poll, clamped 1..50 (default `10`). |

The Python `OutlookConfig` carries only `enabled`, `poll_top`, `allowed_senders`, `require_dmarc` — the
Graph credentials/mailbox are resolved **toolbox-side only**, so the cron/framework registry never holds
the secret.

### Authentication: certificate or client secret

The toolbox uses `@azure/identity`. Configure **one** credential:

```bash
# Option A — client secret
agento config:set outlook/outlook_tenant_id   <tenant>
agento config:set outlook/outlook_client_id   <client-id>
agento config:set outlook/outlook_mailbox_user_id agenty@kazar.com
# The secret is an `obscure` field, so it is auto-encrypted (AES-256-CBC). NEVER pass it as the
# positional value (it would leak into `ps aux` and shell history) — omit the value so agento
# prompts/reads stdin, or pipe it in:
agento config:set outlook/outlook_client_secret              # prompts / reads stdin
# or: printf '%s' "$OUTLOOK_CLIENT_SECRET" | agento config:set outlook/outlook_client_secret

# Option B — certificate (mount the PEM into the toolbox container, then:)
agento config:set outlook/outlook_cert_path /run/secrets/outlook.pem
# (tenant_id / client_id / mailbox_user_id as above)
```

The Azure app registration needs application permission `Mail.ReadWrite` (and `Mail.Send` to reply/send)
with admin consent.

## The inbound security gate

`OutlookPublisher.publish_mail` enforces, in order:

1. **Normalize** the claimed `From` (strip + lowercase).
2. **Allow-list gate** — if the sender does not match `allowed_senders` (glob: `*@kazar.com`, exact
   `sklep@kazarstudio.com`; empty ⇒ block all), the email is skipped and left **unread**. Ordinary
   non-routing — only the domain is logged, no breach.
3. **DMARC gate** — for an allow-listed sender, if `require_dmarc` and the verdict is not `pass`, a
   `SECURITY_BREACH` is logged (structured `event=security_breach reason=dmarc_not_pass`) and **no job is
   published**. The DMARC verdict is parsed from the **first** `Authentication-Results` header (the one
   Exchange Online Protection prepends — lower headers are untrusted, anti-spoof).
4. **Route** — `resolve_agent_view` maps the sender to an `agent_view` via an ingress binding; unrouted
   senders are left unread (operator must `ingress:bind`).
5. **Publish** — one job per message (idempotency `outlook:mail:<id>`), with the `From` stored in
   `job.requester_email` and `requester_trust = domain`.

## Tools are opt-in

All six tools (`outlook_get_message`, `outlook_reply`, `outlook_search_messages`,
`outlook_get_new_messages`, `outlook_send_mail`, `outlook_mark_processed`) ship **disabled**. Enable only
what the agent needs:

```bash
agento tool:enable outlook_get_message    --agent-view <code>
agento tool:enable outlook_reply          --agent-view <code>
agento tool:enable outlook_mark_processed --agent-view <code>
```

`outlook_send_mail` and `outlook_reply` send external email, so they are **recipient-whitelisted** against
`core/email_whitelist` (reply gates the original sender's address) — independent of the inbound
allow-list.

## End-to-end setup

```bash
agento module:enable outlook
agento config:set outlook/enabled 1
# ...auth + mailbox config (above)...
agento config:set outlook/allowed_senders "sklep@kazarstudio.com,mklauza@kazar.com"
agento config:set outlook/require_dmarc 1

# Route the allowed senders to the email-handling agent_view:
agento ingress:bind email sklep@kazarstudio.com <agent_view_code>
agento ingress:bind email mklauza@kazar.com     <agent_view_code>

# Enable the channel-critical tools (one per call):
agento tool:enable outlook_get_message    --agent-view <agent_view_code>
agento tool:enable outlook_reply          --agent-view <agent_view_code>
agento tool:enable outlook_mark_processed --agent-view <agent_view_code>

agento setup:upgrade   # installs the outlook:publish crontab (polls every minute)
```

### Verifying the acceptance criteria

| Scenario | Expected |
|---|---|
| Mail from `sklep@kazarstudio.com`, DMARC pass | Job published; `job.requester_email = sklep@kazarstudio.com` |
| Mail from `test@kazarstudio.com` (not allow-listed) | No job (skipped); no breach |
| Mail claiming `from: sklep@kazarstudio.com`, DMARC **not** confirmed | No job; `SECURITY_BREACH` logged |

Confirm a routed job exists:

```sql
SELECT id, source, reference_id, requester_email, requester_trust, agent_view_id, status
FROM job WHERE source='outlook' ORDER BY id DESC LIMIT 5;
```

## Disabling

`agento module:disable outlook` stops the Python side: the module is skipped during bootstrap, so the
`outlook:publish` cron no longer runs and the channel/publisher are not loaded — **no new jobs are
created**. (The toolbox-side tools and the `/api/outlook/unread` route are not yet torn down on
module-disable — a pending follow-up (Task B5); until then they are not triggered by cron but remain
registered/callable, and the tools stay opt-in / disabled by default.) Disabling is safe — no other
module depends on Outlook.
