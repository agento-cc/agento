# Workspace Build Commands

Materialized workspace builds — pre-built config directories per agent_view. The consumer copies from build dirs into per-job run dirs at execution time, eliminating per-job config generation.

## `workspace:build`

### Usage

```bash
# Build for a specific agent_view
agento workspace:build --agent-view developer

# Build for all active agent_views
agento workspace:build --all

# Force rebuild even if the existing build's checksum matches
agento workspace:build --all --force
```

Shortcut: `ws:b`

### Options

| Flag | Required | Description |
|------|----------|-------------|
| `--agent-view <code>` | One of these | Agent view code to build for |
| `--all` | is required | Build for all active agent_views |
| `--force` | No | Rebuild even if a matching build already exists. Retires the prior same-checksum build (deletes its on-disk directory, marks the DB row `failed`) and produces a fresh `build_id`. Use when something outside the checksum inputs has changed (manual theme edits, external template updates, a file accidentally removed from disk). |

The `--agent-view` and `--all` flags are mutually exclusive; `--force` can be combined with either.

### What It Does

1. Resolves the agent_view and its scoped config overrides (agent_view → workspace → global fallback)
2. Fetches enabled skills for this agent_view (soft dependency on `skill` module)
3. Computes a SHA-256 checksum over sorted config values + skill checksums
4. **Skip check** — if a `ready` build with the same agent_view + checksum exists **and its `build_dir` is intact on disk**, skips the rebuild. `--force` bypasses this check; a missing on-disk directory also forces a rebuild (the stale DB row is retired first).
5. Creates a build directory and applies layers in order:
   - **Theme layering** — copies files from `workspace/theme/`, then overlays workspace-scoped (`workspace/theme/_{ws_code}/`) and agent_view-scoped (`workspace/theme/_{ws_code}/_{av_code}/`) content
   - **Agent CLI configs** — `.claude.json`, `.mcp.json`, `.codex/config.toml` (via provider-specific ConfigWriter)
   - **Instruction files** — `AGENTS.md`, `SOUL.md` from DB if set (otherwise keeps theme files), `CLAUDE.md` always written
   - **Module workspace layering** — copies each enabled module's `workspace/` with the same `_` prefix scoping convention
   - **Skills** — `.claude/skills/<name>/` directories (SKILL.md + companion files like `references/`, `scripts/`) copied from enabled skills
6. Marks the build as `ready` in the `workspace_build` table
7. Updates the `current` symlink to point to the new build

Theme and module workspace directories use the **`_` prefix convention**: directories starting with `_` are scope boundaries (never copied as content), while all other files and directories are content. See [workspace architecture](../architecture/workspace.md) for full details and examples.

Config files are only generated when the corresponding `agent_view/*` config paths exist in scoped overrides. If no `agent_view/*` paths are set for an agent_view, those files are skipped.

### Build Directory Layout

```
/workspace/{workspace_code}/{agent_view_code}/
├── builds/
│   ├── 1/                  # Build ID 1
│   │   ├── .claude.json
│   │   ├── .mcp.json
│   │   ├── .codex/config.toml
│   │   ├── CLAUDE.md
│   │   ├── AGENTS.md
│   │   ├── SOUL.md
│   │   └── .claude/skills/
│   │       └── my_skill.md
│   └── 2/                  # Build ID 2 (newer)
│       └── ...
├── current -> builds/2     # Symlink to latest ready build
└── runs/
    └── {job_id}/           # Per-job isolated copy (created at runtime, cleaned up after)
```

### Events

| Event | Dispatched when |
|-------|-----------------|
| `WorkspaceBuildStartedEvent` | Build begins (status → building) |
| `WorkspaceBuildCompletedEvent` | Build completes or is skipped (status → ready) |
| `WorkspaceBuildFailedEvent` | Build fails (status → failed) |

## `workspace:build-status`

### Usage

```bash
# Show recent builds for all agent_views
agento workspace:build-status

# Filter by agent_view
agento workspace:build-status --agent-view developer
```

Shortcut: `ws:bs`

### Options

| Flag | Required | Description |
|------|----------|-------------|
| `--agent-view <code>` | No | Filter by agent view code |

### Output

Shows the 20 most recent builds:

```
   ID  Agent View            Checksum        Status      Current  Created At
------------------------------------------------------------------------------------------
    2  dev_01             a6ce0904e451  ready              *  2026-04-08 12:55:47
    1  agent01               cb5933ea9df5  ready              *  2026-04-08 12:55:47
```

The `*` in the Current column indicates the build that the `current` symlink points to.

## How It Integrates

At job execution time, the consumer:

1. Calls `get_current_build_dir()` to find the `current` symlink target
2. If a build exists: copies all files into the per-job run directory (`runs/{job_id}/`)
3. If no build exists: falls back to generating configs on-the-fly via `populate_agent_configs()`
4. The agent CLI runs in the isolated run directory
5. The run directory is cleaned up after job completion

Run `workspace:build` after changing agent_view config, skills, or instruction files to ensure the next job picks up the changes.

## Database

The `workspace_build` table tracks build history:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT | Auto-increment primary key |
| `agent_view_id` | INT | Foreign key to `agent_view` |
| `build_dir` | VARCHAR(500) | Full filesystem path to build directory |
| `checksum` | VARCHAR(64) | SHA-256 of config + skill checksums |
| `status` | ENUM | `building`, `ready`, `failed` |
| `created_at` | TIMESTAMP | Build creation time |

Source: `src/agento/modules/workspace_build/src/builder.py`, `src/agento/modules/workspace_build/src/commands/`
