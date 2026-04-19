# Token Management

Agento uses OAuth tokens for Claude Code and OpenAI Codex. **Token contents are stored encrypted in the database** (`oauth_token.credentials`, AES-256-CBC via the framework `Encryptor`). The file passed to `token:register` is only read once — the server no longer needs filesystem access to credentials at runtime.

## Token Lifecycle

```
register → set (primary) → [use] → refresh (if expired) → deregister
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

## Set Primary Token

After registering, mark which token the consumer uses for a given agent type:

```bash
bin/agento token:set claude 1    # Set token ID 1 as primary for Claude
bin/agento token:set codex 2     # Set token ID 2 as primary for Codex
```

Only one token per agent_type can be primary at a time. Rotation respects the sticky primary flag.

## List Tokens

```bash
bin/agento token:list
bin/agento token:list --agent-type claude
bin/agento token:list --json
```

The list output does **not** include `credentials_path` anymore — the credentials live in the DB, encrypted, and are never surfaced by the CLI.

## Refresh an Expired Token

```bash
bin/agento token:refresh 1    # Re-authenticate token ID 1 (interactive)
```

Behaviour: launches OAuth in an isolated temp HOME, then overwrites the stored `credentials` column with the new encrypted blob. The `id` and `label` are preserved, so any downstream references stay valid.

## Usage Stats

```bash
bin/agento token:usage                  # Show usage stats across all providers
bin/agento token:usage --agent-type claude --window 72
```

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
   bin/agento token:set claude 1
   rm /tmp/claude_oauth_1.json   # safe — credentials are already in DB
   ```

## Requirements

- `AGENTO_ENCRYPTION_KEY` must be set (same key used for `core_config_data` obscure fields). See [encryption.md](../config/encryption.md).
- The `oauth_token` table schema is applied via framework migration `019_oauth_token_inline_credentials.sql`. `agento setup:upgrade` applies it automatically.

Source: [src/agento/framework/cli/token.py](../../src/agento/framework/cli/token.py)
