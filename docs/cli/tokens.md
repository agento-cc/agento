# Token Management

Agento uses OAuth tokens for Claude Code and OpenAI Codex. Tokens are stored in the DB and rotated automatically.

## Token Lifecycle

```
register → set (primary) → [use] → refresh (if expired) → deregister
```

## Register a Token

```bash
# From a credentials file (pre-authenticated)
bin/agento token register claude my-token /etc/tokens/claude_oauth_1.json

# Interactive (requires TTY — opens browser for OAuth)
bin/agento token register claude my-token
```

Options:
- `--token-limit N` — usage limit (0 = unlimited)
- `--model MODEL` — model override (e.g. claude-sonnet-4-20250514)

## Set Primary Token

After registering, set which token the consumer uses:

```bash
bin/agento token set claude 1    # Set token ID 1 as primary for Claude
bin/agento token set codex 2     # Set token ID 2 as primary for Codex
```

## List Tokens

```bash
bin/agento token list
bin/agento token list --agent-type claude
bin/agento token list --json
```

## Refresh an Expired Token

```bash
bin/agento token refresh 1    # Re-authenticate token ID 1 (interactive)
```

## Token Rotation

Multi-token rotation distributes load across tokens:

```bash
bin/agento token usage                  # Show usage stats
bin/agento rotate                       # Rotate to least-used token
```

## OAuth Flow for Headless Servers

1. Authenticate locally (machine with browser):
   ```bash
   claude auth login
   cp ~/.claude/.credentials.json tokens/claude_oauth_1.json
   ```

2. Copy to server:
   ```bash
   scp tokens/claude_oauth_1.json user@server:/path/to/agento/tokens/
   ```

3. Register on server:
   ```bash
   bin/agento token register claude my-token /etc/tokens/claude_oauth_1.json
   bin/agento token set claude 1
   ```

Source: [src/agento/framework/cli.py](../../src/agento/framework/cli.py) (token subcommands)
