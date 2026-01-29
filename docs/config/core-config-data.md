# core_config_data

Database table for config overrides — identical to Magento's `core_config_data`.

## Table Schema

```sql
CREATE TABLE core_config_data (
    config_id  INT AUTO_INCREMENT PRIMARY KEY,
    scope      VARCHAR(8) NOT NULL DEFAULT 'default',
    scope_id   INT NOT NULL DEFAULT 0,
    path       VARCHAR(255) NOT NULL,
    value      TEXT NULL,
    encrypted  TINYINT(1) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_scope_path (scope, scope_id, path)
);
```

## Path Format

`{module}/tools/{tool_name}/{field_name}`

```
my_app/tools/mysql_prod/host             → "10.0.0.1"
my_app/tools/mysql_prod/pass             → "aes256:iv:ciphertext" (encrypted=1)
nav_erp/tools/mssql_nav/database        → "NAV_Production"
```

## Scope

`scope` and `scope_id` follow Magento conventions (like `bin/magento config:set --scope=websites --scope-id=1`):

| Scope | scope_id | Description |
|-------|----------|-------------|
| `default` | `0` | Global (default) |
| `workspace` | workspace ID | Per-workspace override |
| `agent_view` | agent_view ID | Per-agent_view override (most specific) |

Resolution order: agent_view → workspace → default (most specific wins).

## CLI

```bash
# Set a global value (auto-encrypts obscure fields)
bin/agento config:set my_app/tools/mysql_prod/pass my-secret

# Set a scoped value (per agent_view)
bin/agento config:set core/allowed_domains "example.com" --scope=agent_view --scope-id=1

# Set a workspace-scoped value
bin/agento config:set core/email_whitelist "*@corp.com" --scope=workspace --scope-id=2

# Get exact path (shows per-scope values, deduplicates if identical)
bin/agento config:get core/allowed_domains
#   core/allowed_domains = example.com              [default]
#   core/allowed_domains = google.com,github.com [agent_view: Agento01]

# Get module tree (shows all config grouped by scope tier)
bin/agento config:get jira
#   jira
#   ├ default
#   │   tools/mysql_magento_prod/host = 10.0.0.1
#   │   tools/mysql_magento_prod/port = 3306     [config.json]
#   ├ agent_view: Agento01 (id=1)
#   │   core/allowed_domains = google.com,github.com
#   └

# Remove a config override (falls back to config.json default)
bin/agento config:remove my_app/tools/mysql_prod/host
bin/agento config:remove core/allowed_domains --scope=agent_view --scope-id=1

# List all values (all scopes)
bin/agento config:list

# List by module prefix
bin/agento config:list jira
```

## Only Overrides

This table stores **only explicit overrides** — values set via `config:set`. Default values from `config.json` are NOT stored here (unlike Magento where defaults are sometimes imported).

The config loader merges at runtime: ENV → DB overrides → config.json defaults.

Source: [src/agento/framework/core_config.py](../../src/agento/framework/core_config.py)
