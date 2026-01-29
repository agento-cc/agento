# Config Commands

Magento-like config management via `core_config_data` DB table.

## config:set

```bash
# Set a database password (auto-encrypted — field type is "obscure")
bin/agento config:set my_ecommerce/tools/mysql_ecom_prod/pass secret123

# Set a plain value
bin/agento config:set my_ecommerce/tools/mysql_ecom_prod/host 10.0.0.1
```

### Path Format

`{module}/tools/{tool_name}/{field_name}`

Module name uses underscores (hyphens converted): `my-ecommerce` → `my_ecommerce`.

### Auto-Encryption

Fields marked as `"type": "obscure"` in module.json are automatically encrypted with AES-256-CBC. See [encryption docs](../config/encryption.md).

## config:get

```bash
bin/agento config:get my_ecommerce/tools/mysql_ecom_prod/host
# Output: 10.0.0.1
```

Returns the DB override value only. Does not show ENV or config.json defaults.

## config:list

```bash
# List all config
bin/agento config:list

# Filter by module prefix
bin/agento config:list my_ecommerce
```

Output:
```
  my_ecommerce/tools/mysql_ecom_prod/host = 10.0.0.1
  my_ecommerce/tools/mysql_ecom_prod/pass = **** [encrypted]
```

## ENV Var Override

ENV vars have the highest priority and override both DB and config.json:

```bash
CONFIG__MY_ECOMMERCE__TOOLS__MYSQL_ECOM_PROD__HOST=10.0.0.99
```

Convention: `CONFIG__{MODULE}__{PATH}` — all uppercase, hyphens → underscores, path separators → `__`.

See [ENV var docs](../config/env-vars.md) for details.
