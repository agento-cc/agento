# Plan: `job_finalize_before` event + `app_monitor` module (MCP verification + email alerts)

## Context

**Why**: Two production incidents (2026-04-24 job 3292 AI-70 mention, follow-up 3368 retry loop) revealed that `claude-cli rc=0 ≠ "agent completed channel-specific work"`.

- 3292: Toolbox MCP registration timed out. Agent burned 21 turns searching for `mcp__toolbox__jira_get_issue` via `ToolSearch`, eventually returned text-only "nie mogę wykonać zadania" and exited rc=0. Consumer wrote `status=SUCCESS`. `idempotency_key` blocked re-publish for that comment → Grzegorz's mention never got a reply.
- 3368: Retry of the same job used `claude-cli --resume {session_id}` — but the resumed session restored broken MCP state from attempt 1. Loop reproduced indefinitely.

**Goal**: Framework-level, channel-agnostic verification gate inserted **before** `UPDATE job SET status='SUCCESS'`. Verifier checks the transcript JSONL for ≥1 successful `mcp__toolbox__*` tool invocation. Missing/empty transcript → veto. Veto → existing retry/dead flow. On verification-driven retry, consumer clears `session_id` so claude-cli starts fresh (fixes the resume-loop bug).

**Scope decisions (from brainstorm)**:
- Channel-agnostic criterion (`mcp__toolbox__*` count > 0). No `if source == 'jira'` branches. Same rule applies to all current/future channels (jira, outlook, bitbucket, gh).
- Verdict-via-mutable-event (no change to `EventManager.dispatch()` contract — observer mutates `event.verdict`).
- New module `app_monitor` (disableable, room for future health checks).
- Bundle with email alerts in same PR.

**Out of scope**:
- Backfill of historical SUCCESS jobs (operator-driven query if/when needed).
- Per-channel deep verification (e.g., "did agent transition to Review"). MCP-usage is the minimal universal invariant.
- Slack/Teams alerts. Email only for now.

---

## Definition of Done

1. Consumer dispatches `job_finalize_before` after rc=0, **before** the SUCCESS UPDATE.
2. `Verdict.fresh_start=True` causes consumer to clear `job.session_id` before re-queue.
3. New module `app_monitor` registers `VerifyMcpUsageObserver` on `job_finalize_before`. If the agent made zero `mcp__toolbox__*` tool calls in the transcript → veto with `NO_MCP_CALLS`, `fresh_start=True`, `retryable=True`.
4. Missing/unreadable transcript → veto with `TRANSCRIPT_MISSING`. Default policy: not retryable (DEAD on first occurrence). Configurable via `app_monitor/missing_transcript_policy` (`dead` | `retry` | `trust`).
5. After `job_finalize_before`, consumer dispatches `job_finalize_after` carrying the verdict (`None` if passed, `Verdict` if vetoed) so downstream observers can react.
6. New `AlertEmailObserver` listens on `job_dead_after`. If `app_monitor/alerts/email_to` and SMTP settings configured → sends plain-text alert. If unconfigured → silent no-op. SMTP failure → logs warning, never propagates.
7. All ≥5 unit test files green. Integration test (fake claude-cli + observer wiring) green.
8. Manual smoke: reproduce incident-3292-shape (rc=0 with no MCP calls) → job ends in DEAD/retry-with-fresh-session per policy.
9. Disabling `app_monitor` (`agento module:disable app_monitor`) returns consumer to pre-change behavior (rc=0 → SUCCESS).

---

## Architecture overview

```
consumer._finalize_job(job, error=None, job_result, elapsed_ms)
  │
  ├─ event = JobFinalizeEvent(job, job_result, elapsed_ms, verdict=None)
  ├─ event_manager.dispatch("job_finalize_before", event)
  │     └─ VerifyMcpUsageObserver.execute(event)
  │           └─ reads JSONL at workspace/.claude/projects/{ws}/{session_id}.jsonl
  │           └─ counts mcp__toolbox__* tool_use lines
  │           └─ if 0 → event.verdict = Verdict(NO_MCP_CALLS, fresh_start=True, retryable=True)
  │           └─ if file missing → event.verdict per missing_transcript_policy
  │
  ├─ if event.verdict is not None:
  │     ├─ if event.verdict.fresh_start: clear job.session_id in DB
  │     ├─ error = JobVerificationFailed(event.verdict)
  │     └─ fall through to existing error/retry/dead path (uses evaluate_retry)
  │
  ├─ else: UPDATE job SET status='SUCCESS' (existing code)
  │
  └─ event_manager.dispatch("job_finalize_after", event)   # always — verdict tells observers what happened

[separately, on terminal failure]
event_manager.dispatch("job_dead_after", JobDeadEvent)
  └─ AlertEmailObserver.execute(event) → smtplib send if configured
```

---

## File-by-file changes

### Framework (modifies existing)

**`src/agento/framework/events.py`** — add three new symbols:
```python
class VerifyReason(str, Enum):
    NO_MCP_CALLS = "no_mcp_calls"
    TRANSCRIPT_MISSING = "transcript_missing"

@dataclass
class Verdict:
    retryable: bool
    reason: VerifyReason
    fresh_start: bool = False
    detail: str | None = None

@dataclass
class JobFinalizeEvent:
    job: Job
    job_result: JobResult | None        # mirror of existing JobSucceededEvent fields
    elapsed_ms: int
    verdict: Verdict | None = None      # mutated by observers
```

**`src/agento/framework/consumer.py`** — modify `_finalize_job` (currently L564-737):
- Around L602 (`if error is None:` branch), **before** the SUCCESS UPDATE:
  1. Build `JobFinalizeEvent` and dispatch `job_finalize_before`.
  2. If `event.verdict is not None`:
     - If `event.verdict.fresh_start`: `UPDATE job SET session_id=NULL WHERE id=%s` (uses existing pymysql connection).
     - Raise/set `error = JobVerificationFailed(event.verdict)` and re-enter the existing error-handling branch (don't duplicate retry/dead logic).
- At end of `_finalize_job` (after status committed, regardless of outcome): dispatch `job_finalize_after` with the same event (verdict set or None). This is in addition to existing `job_succeed_after` / `job_retry_after` / `job_dead_after`.
- New exception class `JobVerificationFailed(Exception)` — defined in `consumer.py` or `events.py`, carries the Verdict. Must be classified as retryable by `evaluate_retry()` only if `verdict.retryable=True`. Easiest: in `retry_policy.evaluate_retry`, add explicit case for `JobVerificationFailed` that delegates to `exc.verdict.retryable`.

**`src/agento/framework/retry_policy.py`** (if separate from consumer.py — confirm during impl):
- Map `JobVerificationFailed` → use `exc.verdict.retryable` as the decision input, otherwise reuse standard retry rules.

### New module `src/agento/modules/app_monitor/`

```
src/agento/modules/app_monitor/
├── module.json
├── events.json
├── config.json
├── README.md           # one-paragraph: what this module does + how to disable
└── src/
    ├── __init__.py
    ├── constants.py            # config path constants (no literals in observer code)
    ├── transcript_reader.py    # iter_tool_uses(session_id, workspace_root) → Iterable[ToolUse]
    ├── verify_mcp_usage.py     # pure function: verify(tool_uses, policy) → Verdict | None
    ├── emailer.py              # send_alert(smtp_cfg, to, subject, body) using smtplib
    └── observers.py            # VerifyMcpUsageObserver, AlertEmailObserver
```

**`module.json`**:
```json
{
  "name": "app_monitor",
  "version": "0.1.0",
  "sequence": [],
  "description": "Application health monitoring. Currently: post-execution job verification (MCP usage check, fresh-start hint on retry, email alerts on DEAD). Future: consumer liveness probes, toolbox connectivity checks, additional health observers."
}
```

**`events.json`**:
```json
{
  "job_finalize_before": [
    {"name": "verify_mcp_usage", "class": "src.observers.VerifyMcpUsageObserver", "order": 100}
  ],
  "job_dead_after": [
    {"name": "alert_email", "class": "src.observers.AlertEmailObserver", "order": 100}
  ]
}
```

**`config.json`** (defaults — NOT mirrored in `system.json`, by design):
```json
{
  "app_monitor": {
    "missing_transcript_policy": "dead",
    "alerts": {
      "email_to": "",
      "smtp_host": "",
      "smtp_port": 587,
      "smtp_user": "",
      "smtp_password": "",
      "smtp_from": "",
      "smtp_tls": true
    }
  }
}
```

**`src/constants.py`** — all config paths as named constants (per project rule: stała, nie literal):
```python
CONFIG_MISSING_TRANSCRIPT_POLICY = "app_monitor/missing_transcript_policy"
CONFIG_ALERT_EMAIL_TO            = "app_monitor/alerts/email_to"
CONFIG_ALERT_SMTP_HOST           = "app_monitor/alerts/smtp_host"
CONFIG_ALERT_SMTP_PORT           = "app_monitor/alerts/smtp_port"
CONFIG_ALERT_SMTP_USER           = "app_monitor/alerts/smtp_user"
CONFIG_ALERT_SMTP_PASSWORD       = "app_monitor/alerts/smtp_password"
CONFIG_ALERT_SMTP_FROM           = "app_monitor/alerts/smtp_from"
CONFIG_ALERT_SMTP_TLS            = "app_monitor/alerts/smtp_tls"

MCP_TOOLBOX_TOOL_PREFIX = "mcp__toolbox__"

POLICY_DEAD  = "dead"
POLICY_RETRY = "retry"
POLICY_TRUST = "trust"
```

**`src/transcript_reader.py`** — small, single-purpose:
```python
@dataclass(frozen=True)
class ToolUse:
    name: str
    tool_use_id: str

def iter_tool_uses(session_id: str, workspace_root: Path) -> Iterable[ToolUse]:
    # path: workspace_root / ".claude" / "projects" / <workspace_name> / f"{session_id}.jsonl"
    # iterate lines, json.loads each, yield ToolUse where message.content[].type == "tool_use"
    # raises FileNotFoundError if missing — caller decides policy
```

**`src/verify_mcp_usage.py`** — pure function (no I/O):
```python
def verify(tool_uses: Iterable[ToolUse]) -> Verdict | None:
    for t in tool_uses:
        if t.name.startswith(MCP_TOOLBOX_TOOL_PREFIX):
            return None  # passed
    return Verdict(retryable=True, reason=VerifyReason.NO_MCP_CALLS, fresh_start=True,
                   detail="agent made zero mcp__toolbox__* tool calls in this session")
```

**`src/emailer.py`** — thin wrapper over `smtplib`:
```python
@dataclass(frozen=True)
class SmtpConfig:
    host: str; port: int; user: str; password: str
    from_addr: str; tls: bool

def send_alert(cfg: SmtpConfig, to: str, subject: str, body: str) -> None:
    # smtplib.SMTP, starttls if cfg.tls, login if cfg.user, sendmail, quit
    # raises on failure — caller catches/logs
```

**`src/observers.py`**:
```python
class VerifyMcpUsageObserver:
    def execute(self, event: JobFinalizeEvent) -> None:
        if event.verdict is not None:
            return  # earlier observer already vetoed
        if not event.job.session_id:
            event.verdict = _apply_missing_transcript_policy()
            return
        try:
            tool_uses = list(iter_tool_uses(event.job.session_id, _workspace_root()))
        except FileNotFoundError:
            event.verdict = _apply_missing_transcript_policy()
            return
        event.verdict = verify(tool_uses)  # None or Verdict

class AlertEmailObserver:
    def execute(self, event: JobDeadEvent) -> None:
        to = _config(CONFIG_ALERT_EMAIL_TO)
        host = _config(CONFIG_ALERT_SMTP_HOST)
        if not to or not host:
            return  # not configured → silent no-op
        try:
            send_alert(...)
        except Exception:
            logger.warning("alert email send failed", exc_info=True)
```

`_apply_missing_transcript_policy()`: reads `CONFIG_MISSING_TRANSCRIPT_POLICY`, returns:
- `POLICY_DEAD` → `Verdict(retryable=False, reason=TRANSCRIPT_MISSING, fresh_start=False)`
- `POLICY_RETRY` → `Verdict(retryable=True, reason=TRANSCRIPT_MISSING, fresh_start=True)`
- `POLICY_TRUST` → `None`

---

## DB migration

**None.** Reuses existing columns: `job.session_id` (nullable, set by `_save_session_id`), `job.status`, `job.attempt`, `job.max_attempts`. No schema changes.

---

## Tests

**Fixtures** (`tests/fixtures/transcripts/`):
- `good_with_mcp.jsonl` — has ≥1 `mcp__toolbox__jira_get_issue` tool_use line
- `bad_no_mcp.jsonl` — only built-in tools (`Read`, `Bash`, `ToolSearch`)
- `bad_text_only.jsonl` — no tool_use at all
- `mixed_other_mcp.jsonl` — has `mcp__context7__*` but no `mcp__toolbox__*` (must veto)

**Unit tests**:

| File | What it covers |
|---|---|
| `tests/unit/modules/app_monitor/test_transcript_reader.py` | Parsing each fixture; `FileNotFoundError` for missing path; tolerance for malformed lines (skip + log, don't crash) |
| `tests/unit/modules/app_monitor/test_verify_mcp_usage.py` | Pure-function: passes on good, vetoes on bad_no_mcp/bad_text_only/mixed_other_mcp |
| `tests/unit/modules/app_monitor/test_observers.py` | `VerifyMcpUsageObserver`: no session_id → policy applied; missing file → policy applied; bad transcript → verdict set; good transcript → verdict stays None. `AlertEmailObserver`: not configured → no-op; configured → emailer called; SMTP raises → warning logged, no propagation |
| `tests/unit/modules/app_monitor/test_emailer.py` | `smtplib.SMTP` mocked (use `unittest.mock`); verify TLS path, login path, message contents |
| `tests/unit/framework/test_consumer_finalize.py` | Dispatch order: `job_finalize_before` fires before SUCCESS update; verdict→error path; `fresh_start=True` clears `session_id`; `job_finalize_after` fires after with correct verdict |

**Integration test** (`tests/integration/test_app_monitor_e2e.py`):
- Spin up consumer with a fake `Runner` that simulates rc=0 with a pre-written JSONL (good vs bad).
- Bad transcript: assert job ends in TODO (retry) with `session_id=NULL` and attempt incremented.
- Good transcript: assert job ends in SUCCESS, `session_id` preserved.
- Missing transcript with policy=dead: assert job ends in DEAD on first try.
- With `email_to` configured + mocked SMTP: assert email sent on DEAD transition.

Total: ~120-150 LOC of test code + ~4 small fixture files.

---

## Verification (manual smoke)

1. `cd docker && docker compose -f docker-compose.dev.yml restart cron` — pick up new module.
2. `agento setup:upgrade --skip-onboarding` — register module (no migrations).
3. **Simulated ghost-success**:
   - Manually craft a JSONL under `workspace/.claude/projects/-workspace/test-session-id.jsonl` containing only `Read`/`Bash` tool_use lines (no `mcp__toolbox__*`).
   - Insert a job row with `session_id='test-session-id'`, `source='jira'`, `reference_id='TEST-1'`.
   - Run a one-shot consumer cycle (or use existing test harness).
   - **Assert**: job moves to TODO (attempt=1, session_id=NULL) after first cycle. After max_attempts cycles → DEAD.
4. **Real claude-cli test**:
   - Disable toolbox temporarily (rename `docker-compose` mount).
   - Trigger a jira mention → publisher enqueues → consumer runs → claude-cli reports "no MCP tools" → exits rc=0 → verifier vetoes → job retries with fresh session → still no MCP → eventually DEAD.
   - Re-enable toolbox, force re-publish (new comment) → success path.
5. **Email alert**:
   - Run a local debug SMTP: `python -m aiosmtpd -n -l 127.0.0.1:1025`.
   - Set `app_monitor/alerts/email_to=ops@example.com`, `smtp_host=127.0.0.1`, `smtp_port=1025`, `smtp_tls=false`, `smtp_from=agento@local`.
   - Trigger any job → DEAD path → confirm aiosmtpd printed the message.
6. **Kill-switch**:
   - `agento module:disable app_monitor`.
   - Re-run step 3 (bad transcript) → job should now go SUCCESS (pre-change behavior). Confirms module is disableable.

---

## Critical files reference (for implementer)

| Concern | File | Notes |
|---|---|---|
| Existing dispatch insertion point | `src/agento/framework/consumer.py:602-625` (`_finalize_job` rc=0 branch) | Inject `job_finalize_before` here, before the UPDATE |
| Existing event class shape | `src/agento/framework/events.py` (look for `JobSucceededEvent`) | Mirror the dataclass style |
| EventManager behavior | `src/agento/framework/event_manager.py:40-51` | Exceptions swallowed — relies on mutable event for veto, that's why Option A was chosen |
| Observer registration loader | `src/agento/framework/bootstrap.py:174-199` (`_load_observers`) | Reads `events.json` of each module; no framework changes needed |
| Retry decision | `src/agento/framework/retry_policy.py::evaluate_retry` (search if not at that path) | Needs awareness of `JobVerificationFailed.verdict.retryable` |
| Session id persistence (already exists) | `src/agento/framework/consumer.py:179-193` (`_save_session_id`) | We only need a complementary "clear" path |
| Transcript path convention | `workspace/.claude/projects/{workspace_name}/{session_id}.jsonl` | Confirmed from sample at `workspace/.claude/projects/-workspace/6ffb8ea7-...jsonl` |
| Jira publisher (no changes needed) | `src/agento/modules/jira/src/channel.py:107-250` | Reference only — verifier is channel-agnostic |
| Config 3-level fallback API | (existing config module — confirm exact import during impl) | Used by observers via constants module |

---

## Implementation order (for executing-plans session)

1. **Framework events** — add `Verdict`, `VerifyReason`, `JobFinalizeEvent`, `JobVerificationFailed` to `events.py`. Unit-testable in isolation.
2. **Framework consumer** — wire `job_finalize_before` dispatch, verdict handling, `session_id` clear, `job_finalize_after`. Update `retry_policy` for new exception.
3. **app_monitor skeleton** — `module.json`, `events.json`, `config.json`, `constants.py`, empty `observers.py`.
4. **transcript_reader.py** + tests (pure parsing, easy).
5. **verify_mcp_usage.py** + tests (pure function).
6. **VerifyMcpUsageObserver** in `observers.py` + tests (mock transcript_reader).
7. **emailer.py** + tests (mock smtplib).
8. **AlertEmailObserver** in `observers.py` + tests.
9. **Integration test** end-to-end.
10. **Manual smoke** per verification section.
11. **Docs**: short paragraph in `docs/architecture/events.md` for new event names; one-paragraph README in `app_monitor/`.

Each step is a clean commit. Final PR = ~10 commits, ~600-800 LOC including tests.

---

## Rollout

- No feature flag. Kill switch = `agento module:disable app_monitor`.
- Tunability via `app_monitor/missing_transcript_policy` (env override possible: `CONFIG__APP_MONITOR__MISSING_TRANSCRIPT_POLICY=trust`).
- Deployment order: ship → observe metrics (count of `job_finalize_after` with non-null verdict in logs) → tune policy if false-positive rate too high → leave on.
- No backwards-compat shim needed (new event, additive).
