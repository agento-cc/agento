# Decision Log

Architectural and technical decisions — *why*, not *what*. For implementation details see [docs/](docs/) and code.

---

## 2026-05-14 — `AGENTO_*` prefix for cron container env vars

- **The bug.** Cron entrypoint persists docker env to `/opt/cron-agent/env` through a prefix whitelist (`MYSQL_|TZ=|DISABLE_LLM=|PROVIDER=|CONFIG__|AGENTO_|PYTHONPATH=`) because the consumer is launched via `su - agent`, which wipes the parent environment. `CONSUMER_MAX_WORKERS`, `CONSUMER_POLL_INTERVAL`, and `JOB_TIMEOUT_SECONDS` weren't in the list, so values set in `docker-compose.override.yml` silently fell back to hardcoded defaults — the consumer always ran with `max_workers=1, poll_interval=5.0s, job_timeout=1200s`.
- **The convention.** Any env var the cron/consumer needs from `docker-compose` must use the `AGENTO_*` prefix. Five offending vars were renamed: `AGENTO_CONSUMER_MAX_WORKERS`, `AGENTO_CONSUMER_POLL_INTERVAL`, `AGENTO_JOB_TIMEOUT_SECONDS`, plus `AGENTO_AGENT_USAGE_WINDOW_HOURS` and `AGENTO_AGENT_ROTATION_INTERVAL_HOURS` (the latter two were surfaced by the regression guard — `AGENT_` doesn't match `AGENTO_`). Externally-conventional vars stay as-is (`MYSQL_*` for the driver, `TZ` for libc, `CONFIG__*` for the public config-fallback contract, `PYTHONPATH`, `PROVIDER`, `DISABLE_LLM`).
- **No backwards-compat aliases.** The old names never reached the consumer in production (that *is* the bug), so nobody is relying on them working — there's no behavior to preserve. Operators upgrading past this release who had the old names set in their compose override should rename them.
- **Regression test pins the contract.** `tests/unit/framework/test_entrypoint_env_whitelist.py` reads the regex out of `entrypoint.sh` and walks every `from_env()` classmethod under `src/agento/framework/` (via AST), collecting each literal var name passed to `os.environ.get(...)`; mismatches fail CI with a clear message. Stops the next framework knob from quietly drifting away from the whitelist — and surfaced the latent `AGENT_*` bug in `agent_manager/config.py` the moment the guard was broadened past `consumer_config.py`.
- **Alternatives considered.** (a) Extend the regex with `CONSUMER_|JOB_TIMEOUT_SECONDS=`: rejected — every new knob would need an entrypoint edit, and the bug class returns. (b) Drop the whitelist and pass everything: rejected — `source $ENV_FILE` breaks on values with quotes/newlines (some `CONFIG__*` values do) and would clobber `PATH`/`HOME`/`SHELL`. (c) Rename `MYSQL_*`/`CONFIG__*`/`TZ` to `AGENTO_*` too: rejected — those are externally-mandated conventions; renaming would break drivers, libc, and the public config contract.
- **Doc.** [docs/architecture/cron-env-contract.md](docs/architecture/cron-env-contract.md) explains the contract end-to-end and lists the migration for operators.

---

## 2026-04-23 — Token pool per provider, LRU selection

- **Dropped `oauth_token.is_primary`.** The sticky "global primary per provider" flag made a single token carry all traffic until manually rotated; a second license sat idle. Multi-license accounts (which are the common case for paid subscriptions) only benefited after the operator ran `token:set`, and even then the sticky winner kept being picked. The flag conflated two concepts — "preferred" and "active" — and couldn't express per-agent_view preferences either.
- **Added `status`, `error_msg`, `expires_at`, `used_at` to `oauth_token`.** `status` (enum `ok|error`) is flipped to `error` automatically when the runner reports an auth failure (Claude's `AuthenticationError` phrases; new Codex stderr patterns). `error_msg` stores the reason for the operator. `expires_at` is pulled from the credentials payload on `token:register` / `token:refresh` so expiry filtering happens in SQL without decrypting every row. `used_at` is the bump timestamp for LRU selection.
- **`select_token(provider)` replaces the rotator.** `SELECT ... ORDER BY used_at IS NULL DESC, used_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED` claims the least-recently-used healthy token atomically, then stamps `used_at = UTC_TIMESTAMP()`. `SKIP LOCKED` prevents two concurrent workers from claiming the same row; the in-line commit makes the bump visible before the runner executes. Why delete `rotator.py` entirely: selection *is* rotation now — the pool fans out naturally without a separate nightly job.
- **Required `agent_view/provider`; no more primary-token fallback.** Consumer raises with an actionable message when `agent_view/provider` is unset. The fallback ("infer provider from whichever token happens to be primary") hid misconfigurations and made agent_view bindings non-authoritative. Operators must now explicitly bind provider per agent_view / workspace / global — which matches every other scoped config in the framework.
- **Auto-detect auth failures → `status='error'` + `TokenAuthFailedEvent`.** When the runner raises `AuthenticationError`, the consumer marks the offending token and dispatches an event for observers. The job still flows through the existing retry pipeline; the next attempt picks a different healthy token via LRU. Dead-letter only when no healthy token remains or retries are exhausted.
- **New CLI: `token:mark-error <id> "<msg>"`, `token:reset <id>`.** Manual levers for operators who want to quarantine or recover a token without re-authenticating. Removed `token:set` (and `rotate`) — they have no meaning under LRU.
- **Alternatives considered.** (a) Keep `is_primary` as a "must-use-first" hint and add LRU as tiebreaker: rejected — still leaves the sticky-preference muddle, just reordered. (b) Per-agent_view token binding table: deferred — buys fine-grained control but costs a new table, a UI surface, and a migration for something no one asked for yet. The per-provider pool handles the real use case (multiple licenses on one account).

---

## 2026-03-31 — UTC-everywhere for timestamps, scoped timezone config

- **All Python datetime calls use `datetime.now(timezone.utc)`, never naive `datetime.now()`.** Bug: container TZ (`Europe/Warsaw`, UTC+2) caused `scheduled_after` on the retry path to be stored 2h ahead of MySQL `NOW()` (UTC). Retries fired late by the timezone offset. Root cause: Python `datetime.now()` returns container-local time, but MySQL TIMESTAMP columns and `NOW()` operate in the server's session timezone (UTC by default).
- **MySQL session pinned to UTC via `init_command="SET time_zone = '+00:00'"`.** Every PyMySQL connection now explicitly sets the session timezone. This makes `NOW()`, `CURRENT_TIMESTAMP`, and parameter interpretation all UTC — regardless of MySQL server config or container TZ. Belt-and-suspenders with the Python fix: even if someone adds a naive datetime, MySQL interprets it as UTC.
- **`core/timezone` scoped config** (IANA timezone string, default `"UTC"`). Lives in the `core` module (`system.json` + `config.json`). Supports per-agent_view / per-workspace / global override via the standard 3-level fallback. Purpose: when code needs to reason in local time (idempotency key bucketing, future display/reporting), it reads the configured timezone rather than relying on container TZ. The `get_timezone()` helper in `config_resolver.py` resolves the value and returns a `ZoneInfo` instance.
- **Why not a `general` module (Magento convention)?** Magento groups locale under `general/locale/timezone`. We chose `core/timezone` because the `core` module already exists and owns framework-level settings. Adding a `general` module for a single field is premature. Can be moved later if `general` gains more fields.
- **Docker TZ env var unchanged.** After the fix, `TZ=Europe/Warsaw` in docker-compose only affects container-level concerns (cron daemon scheduling, log timestamps). All DB-facing code is timezone-independent.
- **Idempotency key bucketing stays UTC for now.** `build_idempotency_key()` uses `datetime.now(timezone.utc)` which is correct and consistent. Timezone-aware bucketing (so "9am Warsaw" cron keys align with configured timezone) deferred until the channel has access to scoped config at publish time.

---

## 2026-03-30 — Unified CLI and two installation paths for beta

- **Python CLI replaces bash wrapper.** The `bin/agento` bash script (821 lines) delegated host-side commands and proxied to Docker for runtime commands. This made `uv tool install agento` useless. Now all commands live in the Python package (`src/agento/framework/cli/` subpackage). `bin/agento` is a thin `exec uv run agento "$@"` wrapper, kept for backward compat.
- **CLI subpackage architecture.** `cli.py` (920 lines) split into `cli/__init__.py` (dispatch), `cli/runtime.py`, `cli/token.py`, `cli/config.py`, `cli/module.py` plus new standalone commands: `cli/doctor.py`, `cli/init.py`, `cli/compose.py`. Two-tier design: standalone commands (doctor, init, up/down) skip `bootstrap()` and heavy imports; runtime commands (consumer, config, token) require DB.
- **Single installation path:** Docker Compose (`agento init` → `agento up`). Includes MySQL in Compose. Zero external deps beyond Docker.
- **Deferred: GHCR images, PyPI publishing.** Beta is not the right time to add release infrastructure. Contracts still stabilizing (Phase 9.5 runtime, upcoming API/admin/broker). Pre-built images add tagging, compatibility, rollback, and pipeline maintenance overhead with little beta-stage payoff.
- **Golden path:** `uv tool install agento → agento init → agento up → agento setup:upgrade`.

---

## 2026-03-25 — Crypt module: adapter pattern for encryption backends

- **Encryptor protocol + get/set_encryptor accessor** in `framework/encryptor.py`. Callers use `get_encryptor().encrypt(value)` instead of importing `crypto.encrypt` directly. Why: the flat utility has no extension point — swapping to vault/KMS later would mean rewriting all callers.
- **AesCbcBackend as default** — wraps existing `crypto.py` (AES-256-CBC, `AGENTO_ENCRYPTION_KEY` env var). Zero behavioral change; purely structural refactor.
- **Fallback to crypto.py** when no backend is registered (tests, scripts that don't boot the module system). Backward compatible.
- **Node.js `crypto.js` unchanged** — toolbox only decrypts. Backend selection happens on the Python side (config:set writes encrypted values). Vault backend for JS is out of scope until needed.
- **Deferred: key rotation, vault adapters, config-driven backend selection.** The adapter pattern makes these additive changes.

---

## 2026-03-24 — Concurrent worker pool with per-run isolation (Phase 9.5)

- **ThreadPoolExecutor, not subprocess pool.** Threads are lightweight coordinators; the actual work runs in CLI subprocesses (Claude Code / Codex). Isolation comes from per-run directories, not process-level separation. Simpler shutdown semantics than subprocess supervision.
- **Per-run directory** `{AGENTO_WORKSPACE_DIR}/{workspace}/{agent_view}/runs/{job_id}/`: each job gets freshly generated `.claude.json`, `.mcp.json`, `.codex/config.toml`, `AGENTS.md`, `SOUL.md`. Eliminates the shared `.claude.json` corruption that forced `concurrency=1`. Directory is cleaned up after job completion.
- **`job.priority`** 0-100 (default 50), stamped at publish time from scoped config path `agent_view/scheduling/priority`. Dequeue uses `ORDER BY priority DESC, created_at ASC`. Changing config does not retroactively affect queued jobs — consistent with Jira's approach to sprint priorities.
- **`AGENTO_CONSUMER_MAX_WORKERS`** env var (default 1, safe to increase now). Originally `CONSUMER_MAX_WORKERS`; renamed in 2026-05 (see [Cron container env prefix convention](#2026-05-14--agento_-prefix-for-cron-container-env-vars) below) because the entrypoint's whitelist dropped non-`AGENTO_*` framework knobs.
- **`agent_view_worker.py` deprecated** — the subprocess-per-agent_view model from Phase 9 is replaced by generic worker slots in the consumer's thread pool.

---

## 2026-03-24 — Deterministic ingress routing (Phase 10)

- **Router protocol + registry** — same extensibility pattern as channels, workflows, and runners. Modules declare routers in `di.json` with an `order` field.
- **All routers run, first match wins** — not short-circuit. Running all detects ambiguity (multiple routers claim the same identity). Ambiguity is logged + evented but the first match (by order) still wins. Why: debugging routing issues requires seeing what all routers think, not just the winner.
- **IdentityRouter as default** (`ingress_identity` table): maps `(identity_type, identity_value)` → `agent_view_id`. Simple, explicit, managed via `ingress:bind` CLI. No ML/semantic routing in MVP.
- **Routing at publish time** — `agent_view_id` is stamped on the job when published, not re-evaluated per execution attempt. Why: routing rules may change between attempts, and a job should stick to its resolved profile for consistency. Also avoids DB calls during the hot execution path.

---

## 2026-03-24 — Per-agent_view instruction files via observer (agent_view module)

- **Observer on `agento_agent_view_run_started`** writes `AGENTS.md`, `SOUL.md`, and `CLAUDE.md` into the run directory. Why observer, not inline in consumer: Magento spirit — modules extend framework behavior via events. Keeps the consumer lean.
- **Content from `core_config_data`** with scoped fallback: `agent_view/instructions/agents_md` and `agent_view/instructions/soul_md`. Follows the same `agent_view/*` config path convention as `agent_view/model`, `agent_view/mcp/servers`, etc.
- **Fallback to workspace file on disk** if no DB value exists. This preserves backward compatibility — existing deployments with `workspace/AGENTS.md` keep working without DB config.

---

## 2026-03-23 — Config fallback simplified to 3 levels

- **Removed field schema defaults** (the 4th fallback level from `system.json` / `module.json` `"default"` keys).
- **3-level fallback**: ENV → DB → `config.json`. Default values live in `config.json` only.
- **Why**: Two places for defaults (schema + config.json) caused confusion and duplication. Every schema default was already mirrored in config.json. Single source of truth is simpler.
- **system.json retains field type/label**: still used for type coercion, encryption detection, and UI. Just no `"default"` key.
- **Migration**: Any `"default"` in schema that wasn't in config.json must be moved there first.

---

## 2026-03-20 — Toolbox JS into modules

- **Toolbox framework at `src/agento/toolbox/`**: peer to `src/agento/framework/` and `src/agento/modules/`. Contains server, config-loader, shared libs, and adapter registry.
- **Module-specific JS in `<module>/toolbox/`**: mirrors `<module>/src/` for Python. Jira MCP tools and REST routes live in `src/agento/modules/jira/toolbox/`. One module = complete package (Python + JS).
- **Core module for generic tools**: `src/agento/modules/core/` provides email, schedule, browser — framework services shipped as a module, like Magento's `Magento_Core`. Keeps toolbox framework lean (only server + adapters).
- **Convention-based discovery** over `di.json` declaration: any `.js` file in `toolbox/` is auto-discovered and must export `register(server, context)`. Simpler for module authors. Explicit is better, but the directory convention is explicit enough — you opt-in by creating the file.
- **Context injection** (`{ log, db, playwright, app }`): module JS tools receive framework utilities via function parameter, not global imports. Makes tools testable in isolation, decouples from file paths.
- **Single `package.json`** in `src/agento/toolbox/`: all JS shares one dependency set. Module JS files use framework-provided libraries. Splitting per module would be premature complexity.
- **`/workspace/tmp` mounted as single volume**: modules create subdirs at runtime (`jira/`, `screenshots/`). Not hardcoded per-module mounts.
- **Adapter registry** (`adapters/index.js`): extracted from old `tools/index.js`. Config-driven tools (mysql, mssql, opensearch) handled separately from module JS tools.

---

## 2026-03-18 — Module system (Phase 0)

- **Magento model**: one module = complete package (channel + workflows + tools + config). Not split by type.
- **Core vs user modules**: core in `src/agento/modules/` (git-tracked), user in `app/code/` (gitignored). User can override core.
- **`module.json` as single manifest**: declares everything a module provides. No multiple XML files like Magento.
- **`importlib` + `sys.path` for loading**: dotted paths in `module.json` relative to module `src/`. No `__init__.py` required in module root.
- **`entry_points["agento.modules"]`** for pip-installable third-party modules (same mechanism as pytest plugins).
- **`BlankWorkflow` in framework, not a module**: utility/testing workflow not tied to any integration.
- **Lazy fallback in registries**: old hardcoded behavior if bootstrap hasn't run (test isolation). Remove once all consumers use bootstrap.
- **Standard PyPA `src/` layout** at repo root (not nested under `docker/`) to enable `pip install agento`.

---

## 2026-03-05 — Agent runner (agent_manager)

- **Runner ABC shared by Claude and Codex**: common interface, replay support, e2e tests. Not two separate unrelated runners.
- **20-minute subprocess timeout**: agents have variable duration, but unbounded is too risky. 20 min covers longest observed tasks.
- **No timeout on ClaudeRunner for job execution**: agent tasks can legitimately run 30s–10min. Premature kill leaves Jira in inconsistent state. Timeout enforcement deferred.
