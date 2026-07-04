# PRD — MCP Toolset Gateway

**Status:** Proposed · **Owner:** mklauza · **Date:** 2026-06-29

Add arbitrary MCP servers (e.g. Figma) to Agento from CLI/TUI, auto-discover their tools (disabled by default), and enable/disable individual tools per scope — without touching framework code.

## Problem

Agento's tools today are hand-written adapters/modules. There is a large ecosystem of third-party MCP servers (Figma, GitHub, Linear, …) we want to use, but no way to plug one in. We need it to be effortless (a few CLI/TUI steps), safe (zero-trust intact), and granular (enable only the tools you want, per agent_view).

## Goals

- Register any MCP server (stdio **or** SSE/HTTP) via one CLI command, and via the admin TUI.
- Auto-discover the server's tools into a registry; **every tool disabled by default** (opt-in / least privilege).
- Enable/disable each tool per scope (`agent_view > workspace > default`), same model as native tools/skills.
- Secrets (API tokens) stay encrypted and **only ever decrypt inside the toolbox** — never reach the agent container.
- No framework changes: ship as one new module + reuse existing config/crypt/build machinery.

## Non-goals

- Direct agent→upstream MCP connections (rejected — see Architecture). Deferred to a possible later Claude-only, secret-free phase.
- Managing the lifecycle of *remote* MCP servers (we connect as a client; we don't host them).
- Per-tool gating via the agent CLI's own allow/deny lists (Codex can't do it; see Architecture).

## Architecture — toolbox-as-MCP-gateway

The **toolbox** (the only container with secrets) acts as an MCP **client** to each registered upstream server, discovers its tools, and **re-exposes only the enabled ones** to the agent over the existing toolbox SSE/HTTP endpoint as passthrough wrappers. The agent's `.mcp.json` continues to point only at `toolbox:3001/sse` — upstream URLs and tokens never appear there.

This is a direct generalization of the existing Playwright integration: [`playwright-client.js`](../../src/agento/toolbox/playwright-client.js) (MCP client) + [`browser.js`](../../src/agento/modules/core/toolbox/browser.js) (passthrough `server.tool → client.callTool`).

**Why gateway and not direct-to-agent — two hard constraints:**

1. **Zero-trust (DECISIONS.md D-5):** a secret-bearing server's token must stay in the toolbox. A direct `.mcp.json` entry would leak it to the credential-free agent.
2. **Per-tool gating reality:** Claude MCP is whole-server on/off; Codex writes only `type`+`url` per server ([codex/config.py:307-309](../../src/agento/modules/codex/src/config.py#L307-L309)) — **no per-tool field exists**. The only place per-tool granularity can be framework-enforced and uniform across providers is the toolbox, where disabled tools are simply never registered.

**Dynamic by design:** the toolbox rebuilds its tool list per agent session ([server.js:82](../../src/agento/toolbox/server.js#L82)), re-reading scoped config each connect. Enabling/disabling a tool therefore applies on the **next agent run — no toolbox restart, no workspace rebuild.**

## Functional requirements

### CLI (new `mcp` module, registered via `di.json`)

| Command | Behavior |
|---|---|
| `mcp:add <name> --transport {stdio\|sse\|http} [--url URL \| --command CMD --args 'a,b'] [--header KEY] [--with-secret]` | Register a server (**disabled**). Secret read via getpass/stdin (never inline argv), stored encrypted. **Auto-runs `mcp:sync <name>` on success.** |
| `mcp:sync [<name>]` | Connect via the toolbox, `listTools()`, upsert tool registry (new/updated-on-checksum/unchanged). |
| `mcp:list [--agent-view <code>]` | List servers + their tools with resolved enabled/disabled at the chosen scope. |
| `mcp:server:enable\|disable <name> [--agent-view\|--scope\|--scope-id]` | Toggle a whole server. |
| `mcp:tool:enable\|disable <namespaced_name> [--agent-view\|…]` | Toggle one tool. |
| `mcp:remove <name>` | Delete registry rows + config (with confirm). |

### Discovery

- A toolbox-only endpoint `POST /internal/mcp/discover?server=<name>` is the sole component that decrypts the upstream token; it returns **tool schemas only, never the token**. `mcp:sync` (and the CLI, which stays credential-free) call it.
- **Auto-sync triggers:** (a) on `mcp:add`; (b) on `setup:upgrade` (observer on `setup_upgrade_after`, like `skill:sync`).

### Enable/disable

- Stored in `core_config_data` (no new table): `mcp_server/{srv}/is_enabled`, `mcp_tool/{srv}__{tool}/is_enabled`. Opt-in: only `'1'` enables. Resolved by the existing `ScopedConfigService` / `isToolEnabled` across the scope chain.
- A tool is exposed to the agent **only if both** its server gate and its tool gate resolve to `'1'`.

### Admin TUI (Phase 2)

- New **MCP** sidebar screen reusing the `EnablementScreen` base ([_enablement.py](../../src/agento/framework/admin/screens/_enablement.py)): scope selector + per-server collapsible tool list with toggles + a per-server **Refresh** (runs sync) and **Remove** (confirm modal).

### Secrets

- Declared `type: obscure` in the mcp module's `system.json` → auto-encrypted (AES-256-CBC) via `config_set_auto_encrypt`, decrypted only in the toolbox. **Default secret scope = agent_view**, never default.

## Data model

- **`mcp_server_registry`** — `id, name UNIQUE, transport ENUM('stdio','sse','http'), url, command, args JSON, header_keys JSON, checksum, last_sync_at, last_error, synced_at, …` (modeled on `skill_registry` + connection columns).
- **`mcp_tool_registry`** — `id, server_id FK, tool_name, namespaced_name UNIQUE (e.g. figma__get_file), description, input_schema JSON, schema_checksum, synced_at`.
- **Naming:** upstream tools are namespaced `<server>__<tool>` to avoid collisions; charset/length validated at sync time.

## Must-handle (engineering invariants)

1. **stdio env hygiene** — child gets `getDefaultEnvironment()` + only explicitly-declared vars. Never `{...process.env}` (would leak every toolbox secret).
2. **Token travels as a transport header / child-env, never as a tool argument** (tool args are logged).
3. **Lift `jsonSchemaToZodShape`** from [browser.js:63](../../src/agento/modules/core/toolbox/browser.js#L63) to a shared toolbox util; reuse its skip-on-bad-schema behavior.
4. **Fail-soft:** a down/slow upstream returns `isError` and never blocks session creation or native tools; reuse the Playwright reconnect/backoff. Pre-connect globally-enabled servers in the `server.js` startup block.
5. **Do not** add MCP tool checksums to `compute_build_checksum` — exposure stays per-session like native tools.

## Phasing

- **P1 (~2–3d):** mcp module (registry + CLI + auto-sync + `mcp-gateway.js` multi-server client + passthrough). stdio + SSE/HTTP. Delivers the Figma outcome.
- **P2:** admin-TUI MCP screen.
- **P3 (optional):** Claude-only direct path for secret-free servers, behind a structurally-enforced secret-free check.

## Success criteria (acceptance)

```bash
agento mcp:add figma --transport sse --url https://mcp.figma.com/sse \
  --header Authorization --with-secret --agent-view developer   # token at hidden prompt; auto-syncs
agento mcp:list --agent-view developer                           # 3 tools, all disabled
agento mcp:server:enable figma          --agent-view developer
agento mcp:tool:enable  figma__get_file --agent-view developer
```
On the next `developer` session, the agent sees **`figma__get_file` only**; the Figma token never appears in the agent's `.mcp.json` or transcript; no restart/rebuild needed. A local stdio server (`mcp:add … --transport stdio --command npx --args '-y,@some/mcp'`) works the same way. Equivalent flow succeeds in the admin TUI.

## Open questions

- Marketplace/registry-assisted `mcp:add` (vs. fully manual server definitions) — out of scope for now.
- Per-server tool-schema caching/staleness policy in the TUI — manual Refresh for P2; revisit if needed.
