# Getting Started

Install Agento and create your first module in 5 minutes.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose V2 (for quickstart path)
- Node.js 18+ (for local dev path)

Run `agento doctor` after installation to verify prerequisites.

## Path A — Docker Compose (recommended)

```bash
# Install the CLI
uv tool install agento              # or: pip install agento

# Scaffold a new project
agento init my-project
cd my-project

# Start the runtime
agento up                            # Starts cron + toolbox + MySQL
agento setup:upgrade                 # Apply migrations, install crontab
```

## Path B — Local dev

For framework contributors and module authors:

```bash
git clone https://github.com/saipix/agento.git && cd agento
agento dev bootstrap                 # Install Python + Node.js deps

# Provide external MySQL connection
cp docker/.env.example .env
nano .env                            # Set CRONDB_HOST, CRONDB_PORT, etc.

agento toolbox start                 # Run toolbox locally
```

## Add Your First Module

```bash
agento module:add my-ecommerce \
  --description="My e-commerce platform" \
  --tool mysql:mysql_ecom_prod:"Production MySQL (read-only)"
```

This creates `app/code/my-ecommerce/` with module.json, config.json, and knowledge/ directory.

## Set Credentials

```bash
# Set database password (auto-encrypted in DB)
agento config:set my_ecommerce/tools/mysql_ecom_prod/pass secret123

# Set host (plain text in DB)
agento config:set my_ecommerce/tools/mysql_ecom_prod/host 10.0.0.1

# Or use ENV vars (highest priority, no DB needed)
# CONFIG__MY_ECOMMERCE__TOOLS__MYSQL_ECOM_PROD__HOST=10.0.0.1
```

## Verify

```bash
agento module:list               # Shows your module with tool count
agento config:list               # Shows all config values
agento token list                # Shows registered agent tokens
agento setup:upgrade --dry-run   # Shows pending work (should be none)
```

## Add Knowledge Base

Place documentation in `app/code/my-ecommerce/knowledge/`:

```bash
# Add system documentation
echo "# My E-commerce\n\nArchitecture overview..." > app/code/my-ecommerce/knowledge/README.md

# Reindex to make it visible to the agent
agento reindex
```

## Register Agent Token

```bash
# On a machine with a browser
claude auth login
cp ~/.claude/.credentials.json tokens/claude_oauth_1.json

# Register and activate
agento token register claude my-token /etc/tokens/claude_oauth_1.json
agento token set claude 1
```

## Next Steps

- [Module Guide](modules/creating-a-module.md) — detailed module creation tutorial
- [Config System](config/) — understand the 3-level fallback
- [CLI Reference](cli/) — all available commands
