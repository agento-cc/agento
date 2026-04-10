# Admin TUI

`agento admin` launches an interactive terminal interface for operational visibility and configuration management. Built with [Textual](https://textual.textualize.io/), it runs inside the Docker cron container and provides keyboard-first navigation with mouse support.

![Admin Config Screen](../images/admin-config.png)

## Usage

```bash
agento admin
```

The command is proxied to the Docker cron container with full TTY support (mouse events, 256-color).

## Navigation

A clickable sidebar on the left provides navigation between screens. Use the mouse or arrow keys + Enter to switch screens. Press `/` to focus the search input on any screen that has one.

Global keys:

| Key | Action |
|-----|--------|
| `r` | Refresh current screen |
| `q` | Quit |
| `Ctrl+X` | Quit (alternative) |
| `Esc` | Close any popup/modal |

## Screens

### Dashboard

Overview of system health and recent activity:

- **System Health** -- database connection status, running jobs count
- **System Info** -- agento version, Python version, loaded module count
- **Recent Jobs** -- last 3 jobs with status, agent view, and timing
- **Tokens** -- registered tokens with type and primary status
- **Agent Views** -- active agent views with workspace assignment

### Jobs

![Admin Jobs Screen](../images/admin-jobs.png)

Full job list with filtering and detail view.

| Key | Action |
|-----|--------|
| `/` | Focus search (filters across all columns) |
| `s` | Cycle status filter: All > TODO > RUNNING > SUCCESS > FAILED > DEAD |
| `Enter` or double-click | Open job detail popup |
| `p` | Replay selected job (with confirmation) |

**Search** filters live across ID, type, status, agent view, and reference ID.

**Job detail popup** shows full metadata: timing, token usage, prompt preview, output preview, and error message.

### Agents

![Admin Agents Screen](../images/admin-agents.png)

Agent view list with workspace assignment, ingress count, and build status.

| Key | Action |
|-----|--------|
| `/` | Focus search (filters by code, workspace, label) |
| `Enter` or double-click | Trigger workspace build (with confirmation) |
| `b` | Trigger workspace build |
| `c` | Jump to Config screen |

**Detail panel** shows code, label, workspace, ingress binding count, and last build status.

### Tokens

![Admin Tokens Screen](../images/admin-tokens.png)

Token list with 24-hour usage statistics.

| Key | Action |
|-----|--------|
| `/` | Focus search (filters by ID, type, label, model) |
| `Enter` or double-click | Open token detail popup |
| `s` | Set selected token as primary (with confirmation) |
| `x` | Deregister token (with confirmation) |

**Detail panel** shows type, model, primary status, enabled status, token limit, usage, and free percentage.

### Config

![Admin Config Screen](../images/admin-config.png)

Schema-driven configuration editor. Shows **all** fields declared in every module's `system.json`, even unset ones.

**Layout:** Module tree (left) | Field table (right) | Detail panel (bottom)

**Scope selector** at the top switches between default, workspace, and agent_view scopes. Fields resolve with the standard fallback: agent_view > workspace > default.

| Key | Action |
|-----|--------|
| `/` | Focus search (filters by field name) |
| `e` or double-click | Edit selected field (opens editor popup) |
| `d` | Delete DB override (field falls back to parent scope, with confirmation) |
| `m` | Toggle mode: Browse All / Overrides Only |

**Source tags** on each field:

| Tag | Meaning |
|-----|---------|
| `[env]` | Value from environment variable (not editable) |
| `[db]` | Set in DB at current scope |
| `[db:inherited]` | Set in a parent scope |
| `[json]` | Default from module's `config.json` |
| `[-]` | No value set anywhere |

**Field editor** provides type-specific inputs:

- `string` -- text input
- `integer` -- text input with numeric validation
- `boolean` -- dropdown (true/false)
- `json` -- multi-line textarea with JSON validation
- `obscure` -- password input (masked)
