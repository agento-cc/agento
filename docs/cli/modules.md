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

Output:
```
  my-ecommerce — My e-commerce platform (2 tools)
  nav-erp — NAV ERP system (1 tools)
```

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
