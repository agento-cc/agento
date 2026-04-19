# Agent Identity (SSH + Credentials)

Each `agent_view` has its own identity: SSH private key, optional public key, optional `~/.ssh/config`, and (via `token:register`) its agent CLI credentials. All identity material is stored **encrypted in the database** and materialized on disk only at workspace-build time, inside the build directory that becomes the agent's `$HOME`.

## Why DB, Not Filesystem

- **Per-agent_view isolation** — each agent_view can have its own git/SSH identity without manual file juggling
- **3-level fallback** — identity resolves through `agent_view → workspace → default` like any other scoped config
- **Encryption at rest** — `ssh_private_key` is stored as an obscure field (AES-256-CBC, same mechanism as other `type: "obscure"` fields in `core_config_data`)
- **Backups** — your SQL backup already captures identity; no separate key-management dance

## Storing an SSH Key

```bash
agento agent_view:identity:set-ssh-key <agent_view_code> <path_to_private_key>
```

Example:

```bash
agento agent_view:identity:set-ssh-key dev_01 ~/.ssh/agent_dev_01
```

The CLI:
1. Reads the private-key file (must contain `PRIVATE KEY`)
2. Encrypts it and stores under `agent_view/identity/ssh_private_key` at scope `agent_view` with `scope_id = <agent_view.id>`
3. If a matching `<key>.pub` exists, stores it as `agent_view/identity/ssh_public_key` (plaintext)

Override the public-key path with `--public-key-path`. Override scope with `--scope default` / `--scope workspace` + `--scope-id <id>` (useful for a workspace-wide fallback key).

## Inspecting Identity

```bash
agento agent_view:identity:show <agent_view_code>
```

Shows the public key (if stored), a fingerprint tag for the private key, and preview lines of `ssh_config` / `known_hosts`. **The private key is never printed.**

## Removing Identity

```bash
agento agent_view:identity:remove-ssh-key <agent_view_code>
```

Deletes all four `agent_view/identity/*` rows for that scope.

## Configuration Fields

Defined in `src/agento/modules/agent_view/system.json`:

| Path | Type | Notes |
|---|---|---|
| `agent_view/identity/ssh_private_key` | `obscure` | Encrypted at rest; decrypted into `<build_dir>/.ssh/id_rsa` (mode 0600) during `workspace:build`. |
| `agent_view/identity/ssh_public_key` | `textarea` | Plaintext; written to `<build_dir>/.ssh/id_rsa.pub`. |
| `agent_view/identity/ssh_config` | `textarea` | Optional — contents of `~/.ssh/config` (Host/IdentityFile blocks for multi-host setups). |
| `agent_view/identity/ssh_known_hosts` | `textarea` | Optional — pre-populated trust entries. |

All four support the standard 3-level scope fallback: `agent_view → workspace → default`.

## Setting Other Fields Directly

For `ssh_config` and `ssh_known_hosts` (not covered by the dedicated CLI), use `config:set`:

```bash
agento config:set agent_view/identity/ssh_config \
  "Host git.my_company.com\n  IdentityFile ~/.ssh/id_rsa\n  User agent" \
  --scope=agent_view --scope-id=<id>

agento config:set agent_view/identity/ssh_known_hosts \
  "$(ssh-keyscan github.com 2>/dev/null)" \
  --scope=default
```

## How It Reaches the Agent Process

1. `agento workspace:build --agent-view <code>` resolves scoped overrides, decrypts the SSH private key, and writes identity files into `workspace/build/<ws>/<av>/builds/<id>/.ssh/` with correct permissions.
2. When the consumer spawns the agent subprocess, it sets `HOME=<build_dir>`. Standard SSH / git tooling picks up `~/.ssh/id_rsa` naturally — no `GIT_SSH_COMMAND` wrapper required.

See [workspace-build.md](../cli/workspace-build.md) for the full build flow.

## Agent Tokens (Claude / Codex)

The same DB-obscured pattern applies to OAuth credentials registered via `token:register`. Credentials are stored inside the `oauth_token.credentials` column (encrypted) instead of referencing a JSON file on disk. See [tokens.md](../cli/tokens.md) for the CLI.
