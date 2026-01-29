# Decision Log

Architectural and technical decisions — *why*, not *what*. For implementation details see [docs/](docs/) and code.

---

## 2026-03-30 — Unified CLI and two installation paths for beta

- **Python CLI replaces bash wrapper.** The `bin/agento` bash script (821 lines) delegated host-side commands and proxied to Docker for runtime commands. This made `uv tool install agento` useless. Now all commands live in the Python package (`src/agento/framework/cli/` subpackage). `bin/agento` is a thin `exec uv run agento "$@"` wrapper, kept for backward compat.
- **CLI subpackage architecture.** `cli.py` (920 lines) split into `cli/__init__.py` (dispatch), `cli/runtime.py`, `cli/token.py`, `cli/config.py`, `cli/module.py` plus new standalone commands: `cli/doctor.py`, `cli/init.py`, `cli/compose.py`, `cli/toolbox.py`, `cli/dev.py`. Two-tier design: standalone commands (doctor, init, up/down) skip `bootstrap()` and heavy imports; runtime commands (consumer, config, token) require DB.
- **Two official installation paths for beta:**
  - **Path A — Docker Compose** (`agento init` → `agento up`): quickstart, self-hosted, demo. Includes MySQL in Compose. Zero external deps beyond Docker.
  - **Path B — Local dev** (`uv`/`pip` + `npm` + external MySQL): framework contributors, module authors. `agento toolbox start` runs Node.js locally with env-file-based config.
- **External MySQL for local dev, no auto-install.** `agento doctor` validates DB connectivity. If missing, prints instructions for providing external connection params. Does not install MySQL, configure system services, or create databases automatically. Aligns with `setup:upgrade` as single entry point for all system updates.
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
- **`job.priority`** 0-100 (default 50), stamped at publish time from scoped config path `agent/scheduling/priority`. Dequeue uses `ORDER BY priority DESC, created_at ASC`. Changing config does not retroactively affect queued jobs — consistent with Jira's approach to sprint priorities.
- **`CONSUMER_MAX_WORKERS`** env var (default 1, safe to increase now). `CONSUMER_CONCURRENCY` kept as backward-compat alias.
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
- **Content from `core_config_data`** with scoped fallback: `agent/instructions/agents_md` and `agent/instructions/soul_md`. Follows the same `agent/*` config path convention as `agent/claude/model`, `agent/mcp/servers`, etc.
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

---

## 2026-03-05 — Mention publisher (jira-mention)

- **Comment-level idempotency key** (`jira:mention:{issue_key}:{comment_id}`), not time-windowed — same mention never processed twice.
- **New toolbox REST endpoint** (`POST /api/jira/issue/comments`): Python code can't use MCP tools directly, needed a REST bridge.
- **Static `accountId` in config** (`jira_assignee_account_id`): dynamic lookup via `/myself` is unnecessary complexity for a rarely-changing value.
- **JQL `comment ~ "{accountId}"`**: `text ~ email` returns 0 results (email not indexed from `[~accountid:...]` markup). Jira indexes the raw accountId string from comment bodies.
- **Reuses `TodoWorkflow`**, no mention-specific workflow needed.

---

## 2026-02-24 — Jira image attachments

- **API v2 over v3** for issue fetching: v3 returns ADF JSON (no direct UUID→attachment mapping). v2 returns wiki markup with `!filename!` directly matching attachment filenames.
- **Download to disk, not base64 in MCP response**: keeps every `jira_get_issue` response lightweight; agent reads images on demand.
- **Shared volume mount** (`../workspace/tmp/jira`): toolbox writes, sandbox reads at same path.
- **Limits: 10 images × 5 MB**: prevents runaway downloads.

---

## 2026-02-22 — Publisher-consumer job queue

- **MySQL `SELECT FOR UPDATE SKIP LOCKED`** over Redis/Celery/Kafka: ~50 jobs/day, 2 workers — no external queue infra needed.
- **PyMySQL over mysql-connector-python**: pure Python, no C extension build in Docker (base image is `node:22-slim`).
- **Consumer in same container as cron**: simpler than a separate service. `wait -n` provides fail-fast if either process dies.
- **Retry via row mutation** (`TODO` + future `scheduled_after`), no separate `RETRYING` status. Backoff: 1m, 5m, 30m.
- **`INSERT IGNORE` on unique key** for idempotency. Time-windowed keys (e.g., `jira:cron:AI-123:20260220_0800`) prevent duplicate jobs from double-fired cron.
- **`source` column** (`'jira'`, `'email'`, …) for future multi-publisher extensibility.
- **JSON structured logs for consumer only**: publisher/sync are short-lived, JSON adds noise there.

---

## 2026-02-19 — Python port (bash → Python)

- **httpx over requests**: native async for future migration, `respx` for clean mocking.
- **Dataclasses over Pydantic**: simple models (<10 fields) from a trusted internal API. Pydantic is 5 MB+ of unneeded validation.
- **Single CLI with subcommands** (`sync`, `exec-cron`, `exec-todo`, `task-list`) instead of 4 bash scripts.
- **Code baked into Docker image** (COPY, not volume mount): venv must be in image. Trade-off: requires rebuild after code changes.
- **Toolbox REST API is the only Jira interface**: cron container has no Jira credentials. All mutations go through Claude CLI via MCP.
