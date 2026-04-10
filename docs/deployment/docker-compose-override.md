# Customizing Docker Compose

Agento uses two Docker Compose files:

| File | Owner | Updated on upgrade? |
|------|-------|---------------------|
| `docker/docker-compose.yml` | Agento | **Yes** — overwritten by `agento upgrade` and `agento install --reinstall` |
| `docker/docker-compose.override.yml` | You | **No** — never touched by Agento |

Docker Compose automatically merges both files when you run `docker compose up`. Your overrides deeply merge into the base config — you can add volumes, environment variables, and new services.

## Adding a volume to an existing service

To mount a custom directory into the toolbox container:

```yaml
# docker/docker-compose.override.yml
services:
  toolbox:
    volumes:
      - ../my-data:/app/my-data:ro
```

The volume is **appended** to the volumes already defined in `docker-compose.yml` — existing mounts are preserved.

## Adding environment variables

```yaml
# docker/docker-compose.override.yml
services:
  cron:
    environment:
      - MY_CUSTOM_VAR=value
```

## Adding a new service

```yaml
# docker/docker-compose.override.yml
services:
  redis:
    image: redis:7-alpine
    networks:
      - agento-net
    restart: unless-stopped
```

Make sure to attach custom services to `agento-net` if they need to communicate with Agento containers.

## Combining multiple overrides

You can add volumes, env vars, and new services in the same file:

```yaml
# docker/docker-compose.override.yml
services:
  toolbox:
    volumes:
      - ../my-tools:/app/my-tools:ro

  cron:
    environment:
      - CUSTOM_FLAG=1

  mobile-emulator:
    image: my-emulator:latest
    ports:
      - "8080:8080"
    networks:
      - agento-net
    restart: unless-stopped
```

## How it works

Docker Compose merges files in this order:

1. `docker-compose.yml` — base (managed by Agento)
2. `docker-compose.override.yml` — your customizations (auto-detected by Docker)

For lists (volumes, environment, ports), values are **appended**. For scalars (image, restart), the override **replaces** the base value. See [Docker Compose documentation](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/) for full merge rules.

## Upgrading

`agento upgrade` overwrites `docker-compose.yml` but never touches `docker-compose.override.yml`. Your customizations survive every upgrade.
