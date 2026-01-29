# agento toolbox start

Run the Node.js toolbox locally (outside Docker).

## Usage

```bash
agento toolbox start
```

## Prerequisites

- Node.js installed
- External MySQL connection configured via env vars

## Environment

The toolbox reads configuration from these sources (highest priority first):

1. Shell environment variables
2. `secrets.env` (project root or parent)
3. `docker/.toolbox.env`
4. `docker/.env`

Required env vars for MySQL connectivity:

```
CRONDB_HOST=localhost
CRONDB_PORT=3306
CRONDB_USER=agento
CRONDB_PASSWORD=secret
CRONDB_DATABASE=agento
```

## Module discovery

The toolbox discovers modules from:

- `CORE_MODULES_DIR` — defaults to `src/agento/modules/` from project root
- `USER_MODULES_DIR` — defaults to `app/code/` from project root

## Default port

Listens on `http://localhost:3001` (configurable via `PORT` env var).
