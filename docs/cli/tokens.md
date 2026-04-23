# Token Management

Agento uses OAuth tokens for Claude Code and OpenAI Codex. **Token contents are stored encrypted in the database** (`oauth_token.credentials`, AES-256-CBC via the framework `Encryptor`). The file passed to `token:register` is only read once — the server no longer needs filesystem access to credentials at runtime.

## Token Pool Model

All tokens registered for a given provider form a **pool**. When the consumer needs a token for a job it calls `select_token(provider)` which picks the **least-recently-used healthy** token (`status='ok'`, not expired) atomically and stamps its `used_at`. Multiple licenses for the same provider therefore share traffic fairly without any "primary" flag.

Health state lives on each row:

| Column       | Meaning                                                                 |
|--------------|-------------------------------------------------------------------------|
| `status`     | `ok` or `error`. Flipped to `error` when the runner sees a 401/expired. |
| `error_msg`  | Operator-visible reason for the latest failure.                         |
| `expires_at` | Credential expiry (from the stored payload). Expired rows are skipped.  |
| `used_at`    | Last time a worker claimed the row — drives LRU ordering.               |

## Token Lifecycle

```
register → [use via LRU] → (auto-flagged error on 401) → refresh | reset → deregister
```

## Register a Token

```bash
# From a credentials file (pre-authenticated). The file is read and its contents
# are encrypted + stored in the database; the file itself is not retained.
bin/agento token:register claude my-token ~/claude_oauth_1.json

# Interactive (requires TTY — opens browser for OAuth)
bin/agento token:register claude my-token
```

Options:
- `--token-limit N` — usage limit (0 = unlimited)
- `--model MODEL` — model override (e.g. `claude-sonnet-4-20250514`)

`register` also resets `status='ok'` and clears any prior `error_msg`, so re-running it on an existing label is a valid recovery path.

## List Tokens

```bash
bin/agento token:list
bin/agento token:list --agent-type claude
bin/agento token:list --json
bin/agento token:list --all    # include disabled tokens
```

Each row shows `status`, `last_used`, `expires`, and (for errored tokens) the truncated `error_msg`. The `credentials` blob is never surfaced.

## Refresh an Expired Token

```bash
bin/agento token:refresh 1    # Re-authenticate token ID 1 (interactive)
```

Refresh overwrites the stored `credentials`, re-parses `expires_at` from the new payload, and resets `status='ok'` / `error_msg=NULL`. The `id` and `label` are preserved so downstream references stay valid.

## Manual Error Control

Useful when you know a license has been revoked or want to take one offline for a bit:

```bash
bin/agento token:mark-error 1 "Revoked by admin 2026-04-23"
bin/agento token:reset 1    # clear status=error, status back to 'ok'
```

`mark-error` stops the pool from handing out that token; `reset` puts it back in rotation without a full OAuth round-trip.

## Usage Stats

```bash
bin/agento token:usage                  # Show usage stats across all providers
bin/agento token:usage --agent-type claude --window 72
```

## Deregister

```bash
bin/agento token:deregister 1   # soft-disable (enabled=FALSE); data retained
```

## Binding a Provider to an `agent_view`

The consumer requires `agent_view/provider` to be set — there is no sticky-primary fallback.

```bash
bin/agento config:set agent_view/provider claude --scope=agent_view --scope-id=1
```

Without this, jobs for that agent_view fail fast with `No agent_view/provider configured`.

## OAuth Flow for Headless Servers

1. Authenticate locally (machine with browser):
   ```bash
   claude auth login
   cp ~/.claude/.credentials.json claude_oauth_1.json
   ```

2. Copy to server (one-shot — the file is only read once during registration):
   ```bash
   scp claude_oauth_1.json user@server:/tmp/
   ```

3. Register on server:
   ```bash
   bin/agento token:register claude my-token /tmp/claude_oauth_1.json
   rm /tmp/claude_oauth_1.json   # safe — credentials are already in DB
   ```

## Requirements

- `AGENTO_ENCRYPTION_KEY` must be set (same key used for `core_config_data` obscure fields). See [encryption.md](../config/encryption.md).
- The `oauth_token` schema is maintained by `019_oauth_token_inline_credentials.sql` + `020_oauth_token_pool.sql`. `agento setup:upgrade` applies both.

Source: [src/agento/framework/cli/token.py](../../src/agento/framework/cli/token.py)
