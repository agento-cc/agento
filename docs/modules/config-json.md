# config.json

Module-level default values (like Magento's `config.xml`). Lowest priority in the config fallback.

## Format

```json
{
  "tools": {
    "mysql_ecom_prod": {
      "host": "10.0.0.1",
      "port": 3306,
      "user": "ai_reader",
      "database": "ecommerce"
    },
    "mysql_ecom_staging": {
      "host": "10.0.0.2",
      "port": 3306,
      "user": "ai_reader",
      "database": "ecommerce"
    }
  }
}
```

## What Goes Here

- Non-secret values: hosts, ports, database names, usernames
- Values that are the same across most deployments

## What Does NOT Go Here

- Passwords, tokens, API keys — use `bin/agento config:set` (stored encrypted in DB)
- Values that change per environment — use ENV vars

## Config Resolution

config.json is the **lowest priority** fallback:

```
1. ENV: CONFIG__MY_ECOMMERCE__TOOLS__MYSQL_ECOM_PROD__HOST=override  (wins)
2. DB:  bin/agento config:set my_ecommerce/tools/mysql_ecom_prod/host 10.0.0.5  (wins over config.json)
3. config.json: {"tools": {"mysql_ecom_prod": {"host": "10.0.0.1"}}}  (lowest)
```

## Reference

See [modules/_example/config.json](../../modules/_example/config.json)
