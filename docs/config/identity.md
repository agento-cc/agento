# Agent Identity (SSH + Credentials)

Each `agent_view` has its own identity: SSH private key, optional public key, optional `~/.ssh/config`, and (via `token:register`) its agent CLI credentials. All identity material is stored **encrypted in the database** and materialized on disk only at workspace-build time, inside the build directory that becomes the agent's `$HOME`.

## Registering a New Agent — Quick Start

Minimum viable onboarding for a fresh `agent_view`, using the interactive paste flow (no host paths leaked into Docker, no volume mounts):

```bash
# 1. Register the agent CLI credentials (Claude / Codex OAuth token)
agento token:register claude dev_01
agento token:set claude <id_printed_above>

# 2. Paste the SSH private key into the encrypted DB field
agento config:set agent_view/identity/ssh_private_key --agent-view dev_01
# → "Paste value for agent_view/identity/ssh_private_key, then press Ctrl+D…"
# <paste the key, press Enter, then Ctrl+D>

# 3. Paste the matching public key (optional but recommended — enables fingerprint display)
agento config:set agent_view/identity/ssh_public_key --agent-view dev_01
# <paste the .pub line, Ctrl+D>

# 4. Verify
agento agent_view:identity:show dev_01

# 5. Materialize the workspace (decrypts key into the build dir that becomes $HOME)
agento workspace:build --agent-view dev_01
```

Everything below explains the mechanism.

## Why DB, Not Filesystem

- **Per-agent_view isolation** — each agent_view can have its own git/SSH identity without manual file juggling
- **3-level fallback** — identity resolves through `agent_view → workspace → default` like any other scoped config
- **Encryption at rest** — `ssh_private_key` is marked `type: "obscure"` in `system.json` and is auto-encrypted by `config:set` (AES-256-CBC, same mechanism as other obscure fields in `core_config_data`)
- **Backups** — your SQL backup already captures identity; no separate key-management dance

## Storing an SSH Key

There is no SSH-specific CLI — identity fields go through the generic `config:set`, which reads the value from the argument, a pipe, or an interactive paste (when stdin is a TTY). Because the field is declared `type: "obscure"`, the value is encrypted automatically.

```bash
# Interactive paste (recommended — no key material in shell history / ps aux)
agento config:set agent_view/identity/ssh_private_key --agent-view dev_01
# Paste key, press Ctrl+D

# Pipe (scripts / CI)
cat ~/.ssh/agent_dev_01 | agento config:set agent_view/identity/ssh_private_key --agent-view dev_01

# Public key (plaintext — same mechanism, different field)
cat ~/.ssh/agent_dev_01.pub | agento config:set agent_view/identity/ssh_public_key --agent-view dev_01
```

### Scope shortcuts

- `--agent-view <code>` — expands to `--scope agent_view --scope-id <lookup>`; mutually exclusive with `--scope-id`.
- `--scope default` / `--scope workspace --scope-id <id>` — for a workspace-wide or global fallback key. Plain `config:set` flags, nothing identity-specific.

## Inspecting Identity

```bash
agento agent_view:identity:show <agent_view_code>
```

Shows the public key (if stored), a fingerprint tag for the private key, and preview lines of `ssh_config` / `known_hosts`. **The private key is never printed.**

## Removing Identity

Identity rows are removed via generic `config:remove`:

```bash
agento config:remove agent_view/identity/ssh_private_key --agent-view dev_01
agento config:remove agent_view/identity/ssh_public_key  --agent-view dev_01
agento config:remove agent_view/identity/ssh_config      --agent-view dev_01
agento config:remove agent_view/identity/ssh_known_hosts --agent-view dev_01
```

## Configuration Fields

Defined in `src/agento/modules/agent_view/system.json`:

| Path | Type | Notes |
|---|---|---|
| `agent_view/identity/ssh_private_key` | `obscure` | Encrypted at rest; decrypted into `<build_dir>/.ssh/id_rsa` (mode 0600) during `workspace:build`. |
| `agent_view/identity/ssh_public_key` | `textarea` | Plaintext; written to `<build_dir>/.ssh/id_rsa.pub`. |
| `agent_view/identity/ssh_config` | `textarea` | Optional — contents of `~/.ssh/config` (Host/IdentityFile blocks for multi-host setups). |
| `agent_view/identity/ssh_known_hosts` | `textarea` | Optional — pre-populated trust entries. |

All four support the standard 3-level scope fallback: `agent_view → workspace → default`.

## How It Reaches the Agent Process

1. `agento workspace:build --agent-view <code>` resolves scoped overrides, decrypts the SSH private key, and writes identity files into `workspace/build/<ws>/<av>/builds/<id>/.ssh/` with correct permissions.
2. When the consumer spawns the agent subprocess, it sets `HOME=<build_dir>`. Standard SSH / git tooling picks up `~/.ssh/id_rsa` naturally — no `GIT_SSH_COMMAND` wrapper required.

See [workspace-build.md](../cli/workspace-build.md) for the full build flow.

## Agent Tokens (Claude / Codex)

The same DB-obscured pattern applies to OAuth credentials registered via `token:register`. Credentials are stored inside the `oauth_token.credentials` column (encrypted) instead of referencing a JSON file on disk. See [tokens.md](../cli/tokens.md) for the CLI.
