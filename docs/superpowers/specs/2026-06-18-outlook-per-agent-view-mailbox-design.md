# Outlook: per-agent_view mailboxes

**Date:** 2026-06-18
**Status:** Design approved — ready for planning
**Author:** brainstorming session (Marcin + Claude)

## Problem

The Outlook channel (added in `2f1df5a`) intentionally uses **one global mailbox**
(`outlook/outlook_mailbox_user_id` at `scope='default', scope_id=0`). The cron job
`outlook:publish` polls that single inbox every minute and fans each unread message out to an
agent_view by **sender** (`resolve_agent_view()` + `ingress:bind email <sender> <view>`).

We want the Jira model instead: **N mailboxes, one per agent_view**, each polled in a loop, where
**the mailbox identifies the target agent_view** (not the sender).

## Guiding principle

Mirror the **existing Jira per-agent_view contract exactly**. Jira already solves "poll a
per-agent_view external system whose secrets live only in the toolbox":

- The publisher loops `get_active_agent_views(conn)` and, per view, calls the toolbox passing **only
  `agent_view_id`** in the request body.
- The toolbox resolves that view's scoped config (host + credentials) via the existing
  `loadScopedDbOverrides(agentViewId)` helper (`src/agento/toolbox/config-loader.js`) — global →
  workspace → agent_view layering.
- **Python holds zero Jira secrets.** Same zero-trust boundary we keep for Outlook.

References: `jira/src/toolbox_client.py` (`agent_view_id` in body), `jira/toolbox/api.js`
(`getJiraConfig(agentViewId)` → `loadScopedDbOverrides`), `jira/src/commands/publish.py`
(`_execute_per_agent_view`).

## Decisions (from brainstorming)

| # | Decision |
|---|----------|
| D1 | **Credential model:** 3-tier fallback for *every* key. Onboarding writes creds at `default`; only `outlook_mailbox_user_id` is written per agent_view. A view *may* override creds, but normally inherits the global Azure app. |
| D2 | **Routing:** the **mailbox determines the agent_view**. The publisher polls view X's mailbox and publishes those jobs directly to view X. `allowed_senders` + DMARC remain purely as the inbound security gate. |
| D3 | **Poll selection / dedupe:** mirror Jira — publisher passes only `agent_view_id`; the idempotency key (`outlook:mail:{message_id}`) prevents duplicate jobs. Iterating views in `id` order makes **lowest agent_view id win** on a shared mailbox, automatically. |
| D4 | **Redundant-poll skip:** the toolbox returns the resolved (non-secret) `mailbox` UPN in the `/api/outlook/unread` response; the publisher keeps a `seen_mailboxes` set and **skips re-processing** a mailbox already handled this run. (Nuance: the redundant Graph *fetch* for a second view sharing a mailbox still happens — we only learn a view's mailbox from its own response — but it produces no duplicate job. Cheap and rare; accepted.) |
| D5 | **Onboarding:** configure **one** mailbox per run. If exactly one active agent_view → save mailbox at `default` (no prompt). If >1 → `terminal.select()` the `agent_view.code` and save the mailbox at that view's scope. No multi-mailbox loop. |
| D6 | **`ingress:bind email`:** Outlook stops using sender→view routing. The framework feature + CLI stay intact for other channels; documented as not-needed for Outlook. |

## Architecture

One cron job `outlook:publish` (`* * * * *`, unchanged) loops internally over active agent_views.
The agent-facing MCP tools (`outlook_get_message` / `outlook_reply` / `outlook_mark_processed`)
need **no change** — they already resolve scoped config under the running job's `agent_view_id`, so
a reply automatically targets the same mailbox the message came from.

### Component changes

#### 1. Publisher loop — `src/agento/modules/outlook/src/commands/publish.py`

```
views = get_active_agent_views(conn)        # ORDER BY id (lowest-id-wins falls out)
seen_mailboxes = set()
for av in views:
    cfg = ScopedConfigService(conn, Scope.AGENT_VIEW, av.id).get_module("outlook")
    if cfg is None or not cfg.enabled:
        continue
    resp = client.list_unread(top=cfg.poll_top, agent_view_id=av.id)   # toolbox resolves mailbox+creds
    mailbox = resp.get("mailbox")
    if not mailbox or mailbox in seen_mailboxes:                       # unconfigured view / shared inbox
        continue
    seen_mailboxes.add(mailbox)
    priority = resolve_publish_priority(conn, av.id)
    for msg in resp.get("messages", []):
        publisher.publish_mail(
            db_config, msg["id"], agent_view_id=av.id,
            sender_email=(msg.get("from") or {}).get("address"),
            dmarc=msg.get("dmarc"),
            allowed_senders=cfg.allowed_senders_list,
            priority=priority, logger=logger,
        )
```

- **No active agent_views → no-op.** With mailbox-determines-view there is nothing to route to;
  this intentionally differs from Jira's "no views → global single run" fallback.
- A per-view failure must `log + continue` (never abort the loop); the toolbox client is always
  closed in a `finally`.
- New optional flag `--agent-view <code>` to run the loop for one view only (manual/debug; mirrors
  `workspace:build --agent-view`).

#### 2. Routing — `src/agento/modules/outlook/src/channel.py`

- `OutlookPublisher.publish_mail()` signature gains `agent_view_id: int` and `priority: int`
  (passed in by the loop). The internal `_resolve_routing()` / `resolve_agent_view(sender)` step is
  **removed**.
- Security gate **unchanged and still fail-closed**, in order:
  1. `allowed_senders` match (empty list blocks all),
  2. DMARC == `pass` (else `SECURITY_BREACH` structured log, leave unread),
  3. publish to the supplied `agent_view_id` with `JobRequester(trust=DOMAIN)`.
- Idempotency key unchanged: `outlook:mail:{message_id}`.
- `publish_todo()` shim updated to forward `agent_view_id` / `priority`.

#### 3. Toolbox REST — `src/agento/modules/outlook/toolbox/api.js` + `api-handlers.js`

- `/api/outlook/unread` reads `agent_view_id` from the request body. Resolve config via
  `loadScopedDbOverrides(agentViewId)` (exactly like `jira/toolbox/api.js`'s `getJiraConfig`)
  instead of global `loadModuleConfigs(null)`. `agent_view_id` absent/null → global scope (preserves
  the onboarding/single-view path).
- Response shape becomes `{ "mailbox": "<resolved UPN>", "messages": [ ... ] }`. `mailbox` is the
  resolved, **non-secret** UPN (for the publisher's `seen_mailboxes`); secrets never leave the
  toolbox.

#### 4. Toolbox client — `src/agento/modules/outlook/src/toolbox_client.py`

- `list_unread(self, top=10, *, agent_view_id=None)` adds `agent_view_id` to the POST body when
  present and returns the full `{mailbox, messages}` object (callers updated for the new shape).

#### 5. Config — `src/agento/modules/outlook/src/config.py`

- `OutlookConfig` keeps omitting the mailbox + Graph secrets (unchanged — toolbox's concern).
- `enabled`, `poll_top`, `allowed_senders` are now read **per view** by resolving the module config
  at `Scope.AGENT_VIEW`. No new fields; no schema change to `system.json` / `config.json`.

#### 6. Onboarding — `src/agento/modules/outlook/src/onboarding.py`

- Credentials (tenant / client / secret-or-cert) → `default` scope (as today).
- Mailbox:
  - exactly one active agent_view → save `outlook_mailbox_user_id` at `default` via the existing
    `config_set` (no prompt);
  - more than one → `terminal.select()` over active `agent_view.code`s, then write the mailbox at
    that view's scope with `scoped_config_set(conn, "outlook/outlook_mailbox_user_id", upn,
    scope=Scope.AGENT_VIEW, scope_id=<av.id>)` (`scoped_config.py`; `encrypted=False` — the UPN is
    not a secret). Mirrors `jira/src/onboarding.py`'s per-view writes.
- Verification poll targets the configured view: `list_unread(top=1, agent_view_id=<view id or None>)`.
- `is_complete()` → base identity + auth present at `default`, **and** at least one
  `outlook/outlook_mailbox_user_id` value exists at *any* scope (default or agent_view).
- Next-steps text drops the `ingress:bind email` instruction (no longer needed); keeps tool-enable +
  `allowed_senders` steps.

#### 7. MCP tools — no code change

`outlook.js` tools already register with the job's `agent_view_id` and resolve scoped config.
Covered by a **verifying test only** (reply/mark target the view's mailbox).

## Out of scope / non-goals

- No per-view *secret* onboarding UX (separate Azure app per view) — supported by the fallback
  mechanism if an operator sets it via `config:set`, but onboarding only writes creds at `default`.
- No removal of `ingress:bind` / `resolve_agent_view` from the framework (other channels use it).
- No change to the consumer, job schema, or MCP tool code.
- No multi-mailbox onboarding loop.

## Testing

Update existing single-mailbox tests and add:

- **Publisher loop:** multi-view fans each mailbox's messages to the correct `agent_view_id`;
  per-view `enabled=false` is skipped; per-view `poll_top` / `allowed_senders` honored.
- **Shared-mailbox dedupe:** two views resolving to the same UPN → processed once, lowest `id` wins,
  config warning logged.
- **No active views → no-op.**
- **Toolbox:** `/api/outlook/unread` with `agent_view_id` resolves scoped mailbox + creds and returns
  `mailbox` in the response; absent `agent_view_id` → global scope.
- **Toolbox client:** `list_unread(agent_view_id=…)` sends it in the body and parses `{mailbox, messages}`.
- **Onboarding:** single-view saves at `default`; multi-view select saves at the chosen view's scope;
  `is_complete()` true once any mailbox exists.
- **MCP tools:** a job under view X has `outlook_reply` target view X's mailbox.
- Update `tests/integration/test_outlook_publish_pipeline.py` for the per-view loop (real DB + routing).

## Migration notes

- Existing single-view deployments: re-run onboarding writes the mailbox at `default`; the single
  view resolves it via fallback. No data migration required.
- A pre-existing global `outlook_mailbox_user_id` at `default` keeps working in single-view
  deployments and acts as a shared fallback in multi-view ones (deduped by `seen_mailboxes`).
- Operators with sender-based `ingress:bind email` rules: those rules become inert for Outlook
  (harmless; can be removed with `ingress:unbind`).
