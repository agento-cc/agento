# Module Commands

## module:add

Create a new module with tool definitions.

```bash
bin/agento module:add my-ecommerce \
  --description="My e-commerce platform" \
  --repo=git@github.com:org/my-ecommerce.git \
  --tool mysql:mysql_ecom_prod:"Production MySQL (read-only)" \
  --tool mysql:mysql_ecom_staging:"Staging MySQL" \
  --tool opensearch:opensearch_ecom:"Product search index"
```

### Tool Format

`--tool TYPE:NAME:DESCRIPTION`

Types: `mysql`, `mssql`, `opensearch`

The command auto-generates field schemas based on tool type:
- **mysql/mssql**: host, port, user, pass (obscure), database
- **opensearch**: host, user, pass (obscure)

### What It Creates

```
modules/my-ecommerce/
  module.json       # Manifest with tool definitions and field schemas
  config.json       # Empty defaults (edit to add non-secret defaults)
  knowledge/
    README.md       # Placeholder
  prompts/
  skills/
```

After creating, the command automatically runs `reindex`.

## module:list

```bash
bin/agento module:list
```

Lists all modules (core + user) in dependency order with their enabled/disabled status.

Output:
```
  ✔ core                 enabled    1.0.0    Framework core services
  ✔ crypt                enabled    1.0.0    Encryption backend
  ✔ jira                 enabled    1.0.0    Jira Cloud integration (requires: core)
  ✘ codex                disabled   1.0.0    OpenAI Codex runtime
```

## module:enable

```bash
bin/agento module:enable <name>
```

Enable a module. Stores state in `app/etc/modules.json`. After enabling, the module's CLI commands, cron jobs, config, routes, and observers are loaded on next bootstrap.

## module:disable

```bash
bin/agento module:disable <name>
```

Disable a module. When disabled, the module is not loaded — its CLI commands, cron jobs, config, routes, and observers are skipped. If another enabled module depends on the disabled one (via `sequence`), `setup:upgrade` and bootstrap will raise an error.

Modules not listed in `app/etc/modules.json` default to **enabled** (backward compatible).

## module:validate

```bash
bin/agento module:validate [name]
```

Validate module structure and manifests. Checks:
- Required fields in `module.json`
- Class paths in `di.json` and `events.json` resolve to `.py` files
- `sequence` entries reference modules that exist on disk
- Field types in `system.json` are valid

## module:remove

```bash
bin/agento module:remove my-ecommerce
```

Deletes `modules/my-ecommerce/` and runs reindex to clean up workspace/systems/.

## reindex

```bash
bin/agento reindex
```

Compiles modules into the runtime workspace (like `bin/magento setup:upgrade`):

1. Scans `modules/*/module.json`
2. Creates symlinks: `modules/{name}/knowledge/` → `workspace/systems/{name}/knowledge/`
3. Copies module.json as system.json (for AGENTS.md template compatibility)
4. Regenerates `workspace/AGENTS.md` from template + all module data

Run reindex after editing module.json, adding knowledge files, or changing module structure.
