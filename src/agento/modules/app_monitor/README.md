# app_monitor

Application health monitoring. Currently two responsibilities:

1. **MCP-health telemetry (`job_finalize_before`)** — when the agent reports
   `rc=0`, `McpHealthTelemetryObserver` records two **independent, nullable**
   per-attempt signals on the `job` row. It is **pure telemetry**: it never sets
   a verdict and never disrupts job flow — an rc=0 job stays a `SUCCESS`.

   | Column | Meaning |
   |---|---|
   | `job.toolbox_mcp_calls` (`INT NULL`) | Count of `mcp__toolbox__*` tool-uses observed in the on-disk session transcript (parsed via the provider's registered `TranscriptReader`). `0` = parsed cleanly, none found. `NULL` = unknown: no reader for the provider, missing/unreadable transcript, or parser drift. |
   | `job.toolbox_mcp_connected` (`BOOLEAN NULL`) | Whether the CLI self-reported the `toolbox` MCP server as connected at session start (from `RunResult.mcp_init`). See semantics below. |

   `toolbox_mcp_connected` semantics — `FALSE` and `NULL` mean different things:
   - **`NULL`** = "we don't know": the provider exposed **no init report at all**
     (e.g. Codex today — see below — or a Claude stream with no `system/init`
     line). This is the explicit unknown state.
   - **`TRUE`** = an init report exists **and** `toolbox` is listed with
     `status="connected"`.
   - **`FALSE`** = an init report exists **and** `toolbox` is present but not
     connected, **or** `toolbox` is absent from the reported servers entirely
     (including the empty-list case — a valid report saying "I started, no MCP
     servers visible"). "Init present, toolbox not visible" is `FALSE`, **not**
     `NULL`.

   Both signals are written on **every** attempt in a single `UPDATE` — including
   to `NULL` — because `job` rows are reused across retries; rewriting both
   columns each attempt prevents a prior attempt's values from going stale.

   **Optional alert** — when `send_alert_on_mcp_issues` is on **and** SMTP is
   configured, one email is sent per attempt if **at least one explicit-bad
   signal** is present: `toolbox_mcp_calls == 0` **OR** `toolbox_mcp_connected IS
   FALSE`. `NULL` ("unknown") never triggers an alert. A combined hit sends a
   single email naming both conditions.

   The transcript parser lives in the agent's module (claude/codex/…); this
   observer resolves one via `get_transcript_reader(provider)`, so the
   framework — and this module — stay agent-agnostic.

   **Codex init signal — empirical finding.** `codex exec --json` (verified
   through 0.128.0 against a real production session, fixture
   `tests/fixtures/codex/real_success_with_mcp.ndjson`) emits **no** session-level
   MCP-server init self-report. The only event types observed are
   `thread.started`, `turn.{started,completed,failed}`, `item.{started,completed}`
   (with `item.type` ∈ {`agent_message`, `command_execution`, `mcp_tool_call`}),
   and `error`. MCP only ever surfaces as per-call `mcp_tool_call` items — which
   report a tool was *invoked*, not whether the server *connected* at startup.
   Consequently `_populate_mcp_init` leaves `RunResult.mcp_init = None` for Codex,
   and `toolbox_mcp_connected` stays `NULL` for codex jobs. Claude *does* emit a
   `system/init` line listing `mcp_servers`, so its column is populated. If a
   future Codex version ships a real init event, wire it into `_populate_mcp_init`
   and add a `tests/fixtures/codex/with_mcp_init.ndjson` fixture.

2. **DEAD-letter alerting (`job_dead_after`)** — `AlertEmailObserver` sends a
   plain-text alert via SMTP when `alerts/email_to` and `alerts/smtp_host`
   are configured. Silent no-op if either is empty; SMTP failures are logged
   but never propagated. (This fires on DEADs caused by *other* framework
   errors — `app_monitor` itself no longer dead-letters anything.)

## Disable

```bash
agento module:disable app_monitor
```

Disabling stops telemetry (columns stay `NULL`) and all email alerts. Job flow
is unaffected — `rc=0` → `SUCCESS` either way.

## Tune

```bash
agento config:set app_monitor/send_alert_on_mcp_issues true
agento config:set app_monitor/alerts/email_to ops@example.com
agento config:set app_monitor/alerts/smtp_host smtp.example.com
```

Env overrides also work, e.g.
`CONFIG__APP_MONITOR__SEND_ALERT_ON_MCP_ISSUES=true`.

A daily MCP-health snapshot:

```sql
SELECT COUNT(*), toolbox_mcp_connected, AVG(toolbox_mcp_calls)
FROM job WHERE created_at > NOW() - INTERVAL 1 DAY
GROUP BY toolbox_mcp_connected;
```
