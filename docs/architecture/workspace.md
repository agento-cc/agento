# Workspace

The workspace is where the agent **reads** from, **writes** to, and **runs**. It's the filesystem surface shared between cron (builder), sandbox (agent), and toolbox (MCP server).

Everything under `workspace/` on the host maps to `/workspace` inside the containers.

## The three-phase model

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│    theme/    │  ───▶ │    build/    │  ───▶ │  artifacts/  │
│              │       │              │       │              │
│  Scaffolding │       │ Per-agent_view│       │   Per-job    │
│   (static)   │       │ (on config   │       │  (scratch +  │
│              │       │    change)   │       │   outputs)   │
└──────────────┘       └──────────────┘       └──────────────┘
    base layer            materialized         per-job overlay
                         configuration          + outputs
```

Each phase has a distinct **lifecycle**, **owner**, and **access pattern**. Understanding this split is the key to understanding how agento works.

---

## Directory layout

```
workspace/
├── theme/                                  # [1] Base scaffolding (static, one per host)
│   ├── CLAUDE.md                           #     → all builds
│   ├── SOUL.md                             #     → all builds
│   ├── app/                                #     → all builds
│   ├── _{workspace_code}/                  #     Workspace-scoped overlay
│   │   └── _{agent_view_code}/             #     Agent_view-scoped overlay
│   └── …
│
├── build/                                  # [2] Materialized per-agent_view builds
│   └── {workspace_code}/                   #     e.g. "default", "it"
│       └── {agent_view_code}/              #     e.g. "dev_01", "qa_01"
│           ├── builds/
│           │   ├── 3/                      #     Old build (kept for rollback/debug)
│           │   ├── 4/
│           │   └── 5/                      #     Most recent
│           │       ├── .claude.json        #     model, systemPrompt, permissions
│           │       ├── .claude/            #     settings.json, skills/<name>/ directories
│           │       ├── .codex/             #     config.toml (model, [mcp_servers.*])
│           │       ├── .mcp.json           #     Toolbox URL with ?agent_view_id=N
│           │       ├── AGENTS.md           #     Resolved instructions
│           │       ├── SOUL.md             #     Resolved personality
│           │       ├── CLAUDE.md           #     Pointer → AGENTS.md
│           │       ├── app/                #     From theme
│           │       └── modules/            #     Module workspace assets (namespaced)
│           │           ├── jira/
│           │           └── core/
│           └── current → builds/5          #     Symlink: which build to use
│
├── artifacts/                              # [3] Per-job scratch/output dirs
│   └── {workspace_code}/
│       └── {agent_view_code}/
│           └── {job_id}/                   #     Created at job start
│               ├── .claude.json            #     Copied from build
│               ├── .claude/                #     Copied from build (agent may write to it)
│               ├── .codex/                 #     Copied from build
│               ├── .mcp.json               #     Copied + ?job_id=N injected
│               ├── AGENTS.md               #     Copied from build
│               ├── SOUL.md                 #     Copied from build
│               ├── CLAUDE.md               #     Copied from build
│               ├── app/         → build/…  #     Symlink (RO)
│               ├── modules/     → build/…  #     Symlink (RO)
│               ├── screenshots/{job_id}/   #     Written by browser_take_screenshot
│               ├── videos/{job_id}/        #     Written by browser_stop_video
│               └── jira/{ISSUE-KEY}/       #     Attachments downloaded via jira_get_issue
│
├── .claude/                                #     Agent CLI session store (Claude)
│   └── projects/-workspace/
│       └── <session_id>.jsonl              #     Conversation transcripts
├── .codex/                                 #     Agent CLI session store (Codex)
│   └── sessions/YYYY/MM/DD/
│       └── rollout-*-<session_id>.jsonl
├── .claude.json                            #     Global Claude CLI state (projects list, etc.)
│
├── tmp/                                    #     Fallback scratch area (used when job_id unknown)
│
└── LESSONS.md                              #     Optional long-term knowledge file
```

### What's shared with the agent's home directory

Inside the containers, these symlinks are created by the cron/sandbox entrypoint:

```
/home/agent/.claude.json  →  /workspace/.claude.json
/home/agent/.claude       →  /workspace/.claude
/home/agent/.codex        →  /workspace/.codex
```

So when the Claude or Codex CLI reads `~/.claude/`, it's actually reading `/workspace/.claude/`. This is how agent session transcripts persist across jobs.

---

## [1] Theme — the base layer

**Source:** `workspace/theme/` on the host. Populated by `agento install` or pre-built for new deployments. Treated as read-only by the build process.

### Theme layering with the `_` prefix convention

The theme directory uses a **layered hierarchy** that lets you scope files to specific workspaces or agent_views. Files live directly at `workspace/theme/`, with `_`-prefixed subdirectories acting as scope overlays:

```
workspace/theme/
├── CLAUDE.md                   # → copied to ALL builds
├── SOUL.md                     # → copied to ALL builds
├── app/                        # → copied to ALL builds
├── .gitkeep                    # NOT copied (dotfile)
├── _it/                        # Workspace "it" scope
│   ├── it-rules.md             # → all agent_views in workspace "it"
│   ├── shared-docs/            # → all agent_views in workspace "it"
│   ├── _dev_01/                # Agent_view "dev_01" scope
│   │   └── dev-specific.md     # → only dev_01 builds
│   └── _qa_01/
│       └── qa-rules.md         # → only qa_01 builds
└── _support/                   # Workspace "support" scope
    └── _qa_01/
        └── support-qa.md
```

**The convention:**

| Pattern | Meaning |
|---------|---------|
| `_` prefixed directories | Scope boundaries — **never** copied as content |
| Everything else (files, non-`_` dirs) | Content — copied at that scope level |
| `.` prefixed items | Always excluded (existing behavior) |

**Three layers applied in order (later overrides earlier):**

1. **Base** — `workspace/theme/*` content → copied to every build
2. **Workspace** — `workspace/theme/_{workspace_code}/*` content → copied to all agent_views in that workspace
3. **Agent view** — `workspace/theme/_{workspace_code}/_{agent_view_code}/*` content → copied to that specific agent_view only

If a file exists at multiple layers, the most specific layer wins. Directories merge across layers (`dirs_exist_ok=True`), so a workspace layer can add files to a directory defined in the base layer without replacing existing files.

If `workspace/theme/` doesn't exist, the theme step is a no-op and the build continues with only module workspaces and DB-sourced instructions.

### Migration from the legacy `_root/` layout

Earlier releases wrapped theme content in `workspace/theme/_root/` and shipped reference templates (`AGENTS.md.template`, `SOUL.md.template`) alongside. Both are removed in the flat layout — theme content now lives directly under `workspace/theme/` (matching how module workspaces work). The `FlattenThemeRoot` data patch runs automatically on `agento setup:upgrade` and:

- Deletes any obsolete `*.template` files at theme root (they were reference-only under the old layout; post-flatten they would leak into builds).
- Moves every item under `workspace/theme/_root/` up one level into `workspace/theme/`.
- If an unexpected destination conflict exists, the move is skipped with a warning and `_root/` is renamed to `workspace/theme/_root.migrated/` for operator inspection.

The patch is idempotent — re-running finds no `_root/` and nothing obsolete to delete, so it no-ops.

### Examples

**Add a knowledge base file to all builds:**
```
workspace/theme/docs/knowledge.md
```

**Add workspace-specific rules:**
```
workspace/theme/_it/magento-guidelines.md
```
→ Appears in all agent_view builds under workspace "it", but not in "support" workspace builds.

**Override SOUL.md for one agent_view:**
```
workspace/theme/_it/_dev_01/SOUL.md
```
→ Only `dev_01` gets this personality. Other agent_views in "it" get the base or workspace-level SOUL.md.

**Fresh install (default workspace + agent01):**
No scope directories needed. Just put files directly in `workspace/theme/` — they'll be the base for all builds. Create `_default/_agent01/` later when you need agent-specific overrides.

### When to edit theme

Use theme layering for **files** that should be part of the agent's workspace (documentation, knowledge base, configuration files). For **config values** (model, personality, MCP servers), prefer DB-scoped config via `agento config:set`.

> **Warning — renaming workspace or agent_view codes is a breaking change:**
> If you rename a workspace or agent_view code in the database, the corresponding `_`-prefixed directories in theme (and module workspaces) are **not** auto-renamed. You must manually rename `_old_code/` → `_new_code/` in all relevant locations. Failure to do so silently drops scoped files from builds.

---

## [2] Build — materialized per-agent_view config

**Source:** Generated by `agento workspace:build --agent-view <code>` (or `--all`).

**What triggers a rebuild:** A change to any scoped config (`core_config_data` rows) that affects this agent_view, OR a change to its enabled skills. Builds are **cached by checksum** — if config hasn't changed, the existing build is reused.

### How a build is constructed

Each build is a full materialization, written in this order:

```
execute_build(agent_view_id):
  1. Compute checksum from:
       - sorted(scoped_config.keys())
       - skill_checksums
     → If a build with this checksum already exists as 'ready', return it. Done.

  2. INSERT workspace_build (status='building'), mkdir builds/{build_id}/

  3. Theme layering (3 layers, each overrides the previous):
       a. Copy workspace/theme/* base content               → build_dir/
       b. Copy workspace/theme/_{ws_code}/* if exists       → build_dir/ (overlay)
       c. Copy workspace/theme/_{ws_code}/_{av_code}/*      → build_dir/ (overlay)

  4. Run ConfigWriter.prepare_workspace() for the agent_view's provider:
       - Claude → writes .claude.json, .claude/settings.json, .mcp.json
       - Codex  → writes .codex/config.toml with [mcp_servers.*]

  5. Write instruction files from DB (if set):
       - AGENTS.md ← DB override │ keep theme file
       - SOUL.md   ← DB override │ keep theme file
       - CLAUDE.md ← always: "Read AGENTS.md" pointer

  6. Module workspace layering (per enabled module, 3 layers each):
       a. Copy workspace/* base content                     → build_dir/modules/{name}/
       b. Copy workspace/_{workspace_code}/* if exists      → build_dir/modules/{name}/
       c. Copy workspace/_{ws_code}/_{av_code}/* if exists  → build_dir/modules/{name}/

  7. Copy enabled skill directories to build_dir/.claude/skills/{skill}/ (SKILL.md + companion files)

  8. UPDATE workspace_build SET status='ready'

  9. Atomically swap the `current` symlink → builds/{build_id}
```

### Override precedence (what wins)

When the same file could come from multiple sources, later steps overwrite earlier ones:

```
LOWEST PRECEDENCE (base)                              HIGHEST PRECEDENCE (wins)

  theme base  <  theme/ws  <  theme/av  <  module base  <  module/ws  <  module/av  <  DB config  <  ENV
  (theme/*)     (theme/_ws/)  (theme/_ws/_av/)                                        (per-scope)   (CONFIG__...)
```

Within each layer, the three-level `_` prefix cascade applies:

```
  base content (no _)  <  _{workspace_code}/  <  _{workspace_code}/_{agent_view_code}/
```

For DB-scoped config specifically, the three-level fallback is:

```
  global (scope_id=0)  <  workspace  <  agent_view
```

So a setting on `agent_view` beats the workspace-wide setting, which beats the global default.

### Module workspace layering

Module `workspace/` directories use the same layered cascade as theme — the module's `workspace/` dir is the base layer, with `_{ws}/` and `_{ws}/_{av}/` as scope overlays:

```
app/code/kazar/workspace/
├── README.md                   # → ALL builds (base content)
├── docs/                       # → ALL builds
│   └── magento-api.md
├── _it/                        # Workspace "it" scope
│   ├── kazar-it-config.md      # → all agent_views in "it"
│   └── _dev_01/                # Agent_view "dev_01" scope
│       └── dev-overrides.md    # → only dev_01 builds
└── _support/
    └── support-rules.md        # → all agent_views in "support"
```

When scope dirs (`_*`) exist in a module workspace, the builder always uses **copy** strategy (even if the global building strategy is "symlink") because symlinks can't merge layers. Modules without scope dirs preserve current symlink behavior.

### Why builds are cached

A build takes seconds (fs copies + small file writes), but it's still non-trivial to do on every job claim. Caching by checksum means:

- **Config unchanged** → build reused, job starts instantly
- **Config changed** → new build created, `current` swapped atomically
- **Old builds kept** on disk for rollback / forensic inspection

### The `current` symlink

```
workspace/build/it/dev_01/current  →  workspace/build/it/dev_01/builds/5
```

This symlink is the **only thing the consumer looks at** to find "the active build." Swapping is atomic (single `rename`), so concurrent jobs never see a torn state.

---

## [3] Artifacts — per-job scratch and outputs

**Source:** Created at job start by the consumer in [`framework/artifacts_dir.py`](../../src/agento/framework/artifacts_dir.py).

**Lifecycle:**

- **Created** at job start. `prepare_artifacts_dir()` wipes any prior content and recreates the dir.
- **Used** throughout the job as the agent's cwd. The agent CLI writes its own scratch here; toolbox tools drop outputs here (screenshots, videos, Jira attachments, etc.).
- **Removed on clean completion.** Jobs that crash or are killed leave the dir behind — useful for post-mortem inspection until the next attempt re-runs and wipes it.

**Why a separate artifacts dir per job:**

1. **Parallel jobs can't clobber each other.** If two jobs ran against the same `build/.../current` directly, they'd both try to mutate `.mcp.json` (injecting their own `job_id`) and race.
2. **Agent CLIs write scratch files.** Claude Code drops `.claude/` state, history, cache. A per-job dir keeps this isolated from the build.
3. **Outputs are scoped per job.** Screenshots, recorded videos, downloaded Jira attachments all land under `artifacts/{ws}/{av}/{job_id}/` so they're trivially attributable.

### The copy/symlink strategy

On job start, the consumer calls `copy_build_to_artifacts_dir(build, artifacts)`:

- **Copied** (small, mutable per-job): items each ConfigWriter declares via `owned_paths()`, plus `CLAUDE.md`, `AGENTS.md`, `SOUL.md`.
- **Symlinked** (large, read-only): everything else — `app/`, `modules/`, skills, theme assets.

So the artifacts dir starts as a **thin overlay** — gigabytes of static build content are symlinked, only hundreds of bytes are actually copied. Output files produced during the job are added on top.

### Runtime param injection

After copying, `ConfigWriter.inject_runtime_params()` mutates the copied config files to append the per-job `job_id`:

```
Before (in build):
  http://toolbox:3001/mcp?agent_view_id=2

After (in artifacts):
  http://toolbox:3001/mcp?agent_view_id=2&job_id=42
```

The toolbox uses `agent_view_id` to look up the agent_view row (and its workspace) in the DB, and `job_id` to scope logs and artifact output paths back to the exact job that made each MCP call. There's no need to pass `workspace_code`/`agent_view_code` on the URL — the toolbox resolves them from `agent_view_id`.

### Cleanup

```
artifacts/it/dev_01/42/  ← created at job start
                         ← agent runs here (cwd = this dir)
                         ← tools drop outputs here (screenshots/, videos/, jira/, …)
                         ← on clean exit: shutil.rmtree()
                         ← on crash: left on disk until next attempt
```

A crashed job's artifacts dir stays around for inspection until the next retry attempt, which wipes it. This is intentional — it lets you diff what the agent wrote vs. what the build provided.

---

## What the agent actually sees

When a Claude or Codex subprocess starts with `cwd = /workspace/artifacts/it/dev_01/42/`:

```bash
$ pwd
/workspace/artifacts/it/dev_01/42

$ ls -la
drwxr-xr-x  .            # this dir
drwxr-xr-x  ..
drwxr-xr-x  .claude/     # copied from build
-rw-r--r--  .claude.json # copied from build
drwxr-xr-x  .codex/      # copied from build
-rw-r--r--  .mcp.json    # copied + ?job_id=42 injected
-rw-r--r--  AGENTS.md
-rw-r--r--  SOUL.md
-rw-r--r--  CLAUDE.md
lrwxrwxrwx  app     →  /workspace/build/it/dev_01/builds/5/app
lrwxrwxrwx  modules →  /workspace/build/it/dev_01/builds/5/modules

$ ls ~/
lrwxrwxrwx  .claude      →  /workspace/.claude       # session transcripts
lrwxrwxrwx  .claude.json →  /workspace/.claude.json  # global CLI state
lrwxrwxrwx  .codex       →  /workspace/.codex        # session transcripts
```

The agent's world is:

- **cwd** = its own job's artifacts dir (config files, instructions, symlinks to build assets, any output it produces)
- **home** = shared CLI session store (globally accessible via symlinks)
- **Everything else** is reached through MCP tool calls to the toolbox

No credentials, no direct DB access, no awareness of other jobs.

---

## Known limitation: session store is not scoped per agent_view

Today `~/.claude/` and `~/.codex/` point to a single workspace-wide dir. All agent_views share the same session transcript pool. Session IDs are UUIDs so there are no collisions, but if you want hard isolation between `dev_01` and `qa_01` conversations, you'd need per-agent_view mounts.

Acceptable today because typical deployments run one agent_view at a time per cron container. This will need revisiting when cron and sandbox separate.

---

## Related docs

- [Module manifest (`di.json`)](../modules/module-json.md) — how modules declare `config_writers`
- [Config system](../config/) — the 3-tier scoped config fallback that feeds builds
- [Containers](containers.md) — volume mounts that expose `workspace/` to each container
- [Publisher–Consumer](publisher-consumer.md) — how jobs are claimed and executed
