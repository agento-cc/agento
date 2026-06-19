# Outlook Email Channel

Poll a Microsoft 365 mailbox **per agent_view** for unread email and turn each authorized message into
a job; the agent reads, replies, and marks messages processed through MCP tools. Like every Agento
channel, all Microsoft Graph secrets and HTTP live in the **Node.js toolbox** (the zero-trust
boundary); the Python module provides the channel, publisher, polling command, onboarding, and
manifests.

> **Routing model:** the **mailbox identifies the agent_view** — there is one mailbox per agent_view,
> and the publisher polls each, publishing that mailbox's jobs to its own view (mirrors the Jira
> per-agent_view contract). This is *not* sender→view routing: `outlook/allowed_senders` + DMARC are
> purely the inbound **security** gate, not routing. (`ingress:bind email …` is no longer used for
> Outlook; existing bindings are inert and removable with `ingress:unbind`.)

> **Security model in one line:** an inbound email creates a job **only** if its `From` is on the
> `outlook/allowed_senders` allow-list **and** the message passes DMARC. DMARC is **always required**
> (not configurable) — an allow-listed sender whose domain publishes a DMARC policy and fails it is
> treated as a spoof: no job, a `SECURITY_BREACH` log, and an ops alert event.

## Architecture

| Concern | Where |
|---|---|
| Graph auth (cert **or** client secret) | `toolbox/graph-auth.js` (`@azure/identity`) |
| 6 MCP tools (read / reply / search / list / send / mark) | `toolbox/outlook.js` |
| Unread-poll REST endpoint (`POST /api/outlook/unread`) + DMARC parse | `toolbox/api.js`, `toolbox/api-handlers.js` |
| Channel prompt fragments + publisher security gate | `src/channel.py` |
| Poll command (`outlook:publish`, cron every minute — loops active agent_views; `--agent-view <code>` for one) | `src/commands/publish.py`, `cron.json` |
| Typed config (no secrets) | `src/config.py` (`OutlookConfig`) |
| Onboarding | `src/onboarding.py` |

## Configuration

Set via `agento config:set outlook/<key> <value>` (or `CONFIG__OUTLOOK__<KEY>` env). Keys:

| Key | Type | Notes |
|---|---|---|
| `outlook/enabled` | bool | Channel switch — resolved **per agent_view** (set at the view's scope; default `false`). The publisher skips any view whose resolved value is falsy. |
| `outlook/outlook_tenant_id` | string | Azure AD tenant ID (normally at `default` — the global Azure app). |
| `outlook/outlook_client_id` | string | Azure app (client) ID (normally at `default`). |
| `outlook/outlook_client_secret` | **obscure** | Client secret (encrypted at rest). Use **either** this **or** a cert. |
| `outlook/outlook_cert_pem` | **obscure** | Certificate PEM **contents** (cert + private key), encrypted at rest. Takes precedence over the secret when both are set. No file mount. |
| `outlook/outlook_cert_password` | **obscure** | Optional passphrase for an encrypted PEM (leave unset if the PEM is unencrypted). |
| `outlook/outlook_mailbox_user_id` | string | Mailbox UPN to poll — **per agent_view** (the mailbox identifies the target view). Set at the view's scope for multi-view; `default` works for a single-view deployment (resolved via fallback). |
| `outlook/allowed_senders` | string | **Comma-separated allow-list** of `From` addresses, resolved **per view**. Supports **glob wildcards** (`*@mycompany.com` matches any local part at that domain; `*` never crosses the `@`) and exact addresses. **Empty = block all.** |
| `outlook/poll_top` | int | Max unread fetched per poll, resolved per view, clamped 1..50 (default `10`). |
| `outlook/restrict_read_to_allowed_senders` | bool | **Default `true`.** When on, the agent read tools (`outlook_get_message` / `outlook_search_messages` / `outlook_get_new_messages`) only surface mail whose sender is on `allowed_senders` — empty `allowed_senders` ⇒ block all reads (fail-closed). Disabling it (`false`) lets the agent read **any** message in the mailbox, including spoofed / non-allow-listed mail — a documented **security risk**. |

A DMARC pass is **always required** for allow-listed senders — it is not a config option (see the security gate below).

All per-view keys resolve with the standard 3-tier fallback **agent_view → workspace → default**, so a
view normally inherits the global Azure app credentials and overrides only its `outlook_mailbox_user_id`
(and, if it differs, `enabled`/`allowed_senders`). Two views resolving to the **same** mailbox UPN are
deduped at poll time — the **lowest agent_view id wins** and a warning is logged.

The Python `OutlookConfig` carries only `enabled`, `poll_top`, `allowed_senders` — the
Graph credentials/mailbox are resolved **toolbox-side only**, so the cron/framework registry never holds
the secret.

### Authentication: certificate or client secret

The toolbox uses `@azure/identity`. Configure **one** credential:

```bash
# Option A — client secret
agento config:set outlook/outlook_tenant_id   <tenant>
agento config:set outlook/outlook_client_id   <client-id>
agento config:set outlook/outlook_mailbox_user_id agenty@mycompany.com
# The secret is an `obscure` field, so it is auto-encrypted (AES-256-CBC). NEVER pass it as the
# positional value (it would leak into `ps aux` and shell history) — omit the value so agento
# prompts/reads stdin, or pipe it in:
agento config:set outlook/outlook_client_secret              # prompts / reads stdin
# or: printf '%s' "$OUTLOOK_CLIENT_SECRET" | agento config:set outlook/outlook_client_secret

# Option B — certificate (PEM contents stored encrypted; NO file mount)
# Easiest: run `agento setup:upgrade`, choose Outlook -> "Certificate (paste PEM contents)",
# paste the full PEM (cert + private key) ending with a line "END", and enter the passphrase if any.
# Or set it manually — outlook_cert_pem is an `obscure` field, so omit the value and let agento
# read it from stdin (NEVER pass a path or the contents as a positional value):
agento config:set outlook/outlook_cert_pem < /path/to/app.pem
agento config:set outlook/outlook_cert_password            # only if the PEM is encrypted
# (tenant_id / client_id / mailbox_user_id as above)
```

**Configure exactly one auth method.** The certificate takes precedence over the client secret in
`graph-auth.js` when both are present. Onboarding clears the other method's keys automatically when you
switch, but if you configure manually you must do it yourself — when switching, `config:remove` the keys
you are no longer using (`outlook/outlook_cert_pem` + `outlook/outlook_cert_password`, or
`outlook/outlook_client_secret`) so stale credentials can't silently win. Config resolves
**ENV → DB → `config.json`**, so if you ever set a `CONFIG__OUTLOOK__OUTLOOK_*` override (e.g.
`CONFIG__OUTLOOK__OUTLOOK_CERT_PEM`), unset that too — `config:remove` only clears the DB row and the
ENV value outranks it.

The Azure app registration needs application permission `Mail.ReadWrite` (and `Mail.Send` to reply/send)
with admin consent.

## The inbound security gate

`OutlookPublisher.publish_mail` enforces, in order:

1. **Normalize** the claimed `From` (strip + lowercase).
2. **Allow-list gate** — if the sender does not match `allowed_senders` (glob: `*@mycompany.com`, exact
   `sklep@mycompanystudio.com`; empty ⇒ block all), the email is skipped and left **unread**. Ordinary
   non-routing — only the domain is logged, no breach.
3. **DMARC gate (always on)** — for an allow-listed sender the verdict must be `pass`, or **no job is
   published** (fail-closed, no opt-out). An **explicit failure** (`fail`/`quarantine`/`reject`) on a
   domain that publishes a DMARC policy is a probable spoof: a `SECURITY_BREACH` is logged (structured
   `event=security_breach reason=dmarc_not_pass`) **and** a framework `security_breach_after` event is
   dispatched (app_monitor's `SecurityBreachAlertObserver` emails ops when `alerts/*` is configured).
   Any other non-pass (`none`/`bestguesspass`/`temperror`/missing) just means the domain has no usable
   DMARC policy — info log only, no breach, no alert, still no job. The verdict is parsed from the
   **first** `Authentication-Results` header (the one Exchange Online Protection prepends — lower
   headers are untrusted, anti-spoof).
4. **Publish to the mailbox's agent_view** — the **mailbox identifies the agent_view**: the publisher
   loop polls view X's mailbox and publishes those jobs directly to view X (no sender→view routing).
   One job per message (idempotency `outlook:mail:<id>`), with the `From` stored in
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

The **read** tools (`outlook_get_message`, `outlook_search_messages`, `outlook_get_new_messages`) are
gated by `outlook/restrict_read_to_allowed_senders` (default **on**): they only surface mail from a
sender on `outlook/allowed_senders`, so an enabled read tool can't expose mail the channel would never
have turned into a job (incl. spoofed / DMARC-failed mail sharing the mailbox). Empty `allowed_senders`
⇒ no readable mail (fail-closed). Disabling the flag is a documented security risk.

## End-to-end setup

```bash
agento module:enable outlook
# Global Azure app credentials at the default scope (one app shared across views) — see
# "Authentication" above: tenant_id / client_id / client_secret-or-cert_pem.

# Easiest: `agento setup:upgrade` runs onboarding — it stores the creds at default and, when there is
# more than one active agent_view, prompts you to pick which view owns the mailbox (writing it at that
# view's scope). The manual equivalent, per agent_view (omit --scope/--scope-id for a single-view
# deployment to use the default scope):
agento config:set outlook/outlook_mailbox_user_id agenty@mycompany.com --scope agent_view --scope-id <id>
agento config:set outlook/allowed_senders "sklep@mycompanystudio.com,mklauza@mycompany.com,*@mycompany.com" --scope agent_view --scope-id <id>
agento config:set outlook/enabled 1 --scope agent_view --scope-id <id>

# Enable the channel-critical tools (one per call):
agento tool:enable outlook_get_message    --agent-view <agent_view_code>
agento tool:enable outlook_reply          --agent-view <agent_view_code>
agento tool:enable outlook_mark_processed --agent-view <agent_view_code>

agento setup:upgrade   # installs the outlook:publish crontab (polls every active view's mailbox every minute)
```

(No `ingress:bind email` step — the mailbox identifies the agent_view. To run the loop for one view
manually: `agento outlook:publish --agent-view <code>`.)

### Verifying the acceptance criteria

| Scenario | Expected |
|---|---|
| Mail from `sklep@mycompanystudio.com`, DMARC pass | Job published; `job.requester_email = sklep@mycompanystudio.com` |
| Mail from `test@mycompanystudio.com` (not allow-listed) | No job (skipped); no breach |
| Mail claiming `from: sklep@mycompanystudio.com`, DMARC **not** confirmed | No job; `SECURITY_BREACH` logged |

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
