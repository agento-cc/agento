# app_monitor

Application health monitoring. Currently two responsibilities:

1. **Post-execution verification (`job_finalize_before`)** — when claude-cli
   reports `rc=0`, `VerifyMcpUsageObserver` parses the session transcript
   JSONL and counts `mcp__toolbox__*` tool calls. Zero calls → veto with
   `fresh_start=True`, sending the job back through the retry path with a
   cleared `session_id` (preventing the resume-loop bug from incident 3368).
   Missing transcript → policy-driven veto (`missing_transcript_policy`:
   `dead` / `retry` / `trust`).

2. **DEAD-letter alerting (`job_dead_after`)** — `AlertEmailObserver` sends a
   plain-text alert via SMTP when `alerts/email_to` and `alerts/smtp_host`
   are configured. Silent no-op if either is empty; SMTP failures are logged
   but never propagated.

## Disable

```bash
agento module:disable app_monitor
```

Disabling restores pre-change consumer behavior: `rc=0` → `SUCCESS`, no email
alerts on DEAD.

## Tune

```bash
agento config:set app_monitor/missing_transcript_policy retry
agento config:set app_monitor/alerts/email_to ops@example.com
agento config:set app_monitor/alerts/smtp_host smtp.example.com
```

Env overrides also work, e.g.
`CONFIG__APP_MONITOR__MISSING_TRANSCRIPT_POLICY=trust`.
