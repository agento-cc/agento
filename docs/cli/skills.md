# Skill Commands

Manage the skill registry — scan skills from disk, list registered skills, and enable/disable per agent_view using scoped config.

## `skill:sync`

### Usage

```bash
agento skill:sync
```

Shortcut: `sk:sy`

### What It Does

Scans the skills directory (`workspace/.claude/skills/` by default) plus every enabled module's `skills/` directory, and syncs discovered skills to the database registry. A skill is a directory containing a `SKILL.md` file; the directory name becomes the skill name.

Prints a summary after syncing:

```
Synced: 2 new, 1 updated, 3 unchanged
```

The skills directory is configurable via the `skill` module's `config.json` (`skills_dir` key).

## `skill:list`

### Usage

```bash
# List all skills (global status)
agento skill:list

# List skills with status scoped to an agent_view
agento skill:list --agent-view developer
```

Shortcut: `sk:li`

### Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--agent-view <code>` | No | — | Show enabled/disabled status for this agent_view |

### Output

```
  my_skill                       enabled    Helps with code review
  debugging                      disabled   Systematic debugging approach
  brainstorming                  enabled    Creative exploration before implementation
```

Skills are **enabled by default**. A skill is disabled only when `skill/{name}/is_enabled` is explicitly set to `0` in scoped config.

If no skills are registered, prints: `No skills registered. Run skill:sync first.`

## `skill:enable`

### Usage

```bash
# Enable at default scope
agento skill:enable my_skill

# Enable for a specific agent_view
agento skill:enable my_skill --agent-view developer

# Enable at explicit scope
agento skill:enable my_skill --scope workspace --scope-id 1
```

Shortcut: `sk:en`

### Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `skill_name` | Yes | — | Name of the skill to enable |
| `--agent-view <code>` | No | — | Shortcut for `--scope agent_view` (resolves code → ID) |
| `--scope` | No | `default` | Config scope: `default`, `workspace`, `agent_view` |
| `--scope-id` | No | `0` | Scope ID |

### What It Does

Sets `skill/{name}/is_enabled = 1` in scoped config (`core_config_data` table).

## `skill:disable`

### Usage

```bash
agento skill:disable my_skill
agento skill:disable my_skill --agent-view developer
```

Shortcut: `sk:di`

### Options

Same as `skill:enable`.

### What It Does

Sets `skill/{name}/is_enabled = 0` in scoped config.

## How Skills Work

### Disk Layout

Skills live in the configured skills directory (default: `workspace/.claude/skills/`) and in any enabled module's `skills/` directory (`src/agento/modules/<mod>/skills/`, `app/code/<mod>/skills/`). Each skill is a directory containing a `SKILL.md` file plus any companion files (references, scripts, resources):

```
workspace/.claude/skills/
├── my-skill/
│   └── SKILL.md
├── debugging/
│   ├── SKILL.md
│   └── references/
│       └── patterns.md
└── brainstorming/
    └── SKILL.md
```

The directory name becomes the skill name. On name collisions, user-workspace skills win over module skills (see `sync_skills_multi` in the registry).

### Registry

`skill:sync` scans each configured directory for `<name>/SKILL.md`, computes a SHA-256 checksum of the `SKILL.md` content, and upserts into the `skill` database table. This lets the framework track which skills are available and detect changes.

> **Companion-file caveat:** the checksum today covers `SKILL.md` only. Edits to companion files (`references/*`, `scripts/*`) don't invalidate the build — run `agento workspace:build --force` to pick them up.

### Scoped Config

Enable/disable uses the standard 3-level scoped config system:

- Config path: `skill/{name}/is_enabled`
- Value: `1` (enabled) or `0` (disabled)
- Scopes: `default` → `workspace` → `agent_view` (most specific wins)

Skills are enabled by default — no config entry needed. Only explicitly disabled skills are excluded.

### Integration with Workspace Builds

When `workspace:build` runs, it fetches enabled skills for the target agent_view and copies each skill's source directory into the build at `.claude/skills/{name}/`. The full tree (`SKILL.md` + any companion files) is preserved so the agent CLI finds skills in the format Claude Code expects at runtime.

Source: `src/agento/modules/skill/src/registry.py`, `src/agento/modules/skill/src/commands/`
