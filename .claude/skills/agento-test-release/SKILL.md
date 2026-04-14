---
name: agento-test-release
description: Build and locally install Agento for testing. Use this skill when the user wants to test a release locally, try the built package, do a test install, or says things like "test release", "test install", "build and install locally", "try the package". Even just "test build" should trigger this skill.
---

# Test Release Workflow

Build Agento and install it locally via `uv tool install` for manual testing before a real release.

## Step 1: Build the Python package

```bash
uv build
```

This produces `.whl` and `.tar.gz` files in `dist/`.

## Step 2: Find the latest wheel

List `dist/` sorted by modification time and pick the newest `.whl` file:

```bash
ls -t dist/*.whl | head -1
```

## Step 3: Install CLI locally

Install the wheel using `uv tool install` with `--force` to replace any previous installation:

```bash
uv tool install --force dist/<latest>.whl
```

## Step 4: Build Docker images locally

Build all 3 images for native architecture (no emulation warnings on ARM Macs).

**Order matters:** sandbox first (base image), then cron and toolbox in parallel.

```bash
# 1. Sandbox (base for cron)
docker build -t agento-sandbox:dev -f docker/sandbox/Dockerfile docker/sandbox/

# 2. Cron (depends on sandbox) — tag must match AGENTO_VERSION in .env
docker build -t ghcr.io/agento-cc/agento-cron:<VERSION> \
  --build-arg SANDBOX_IMAGE=agento-sandbox:dev \
  -f docker/cron/Dockerfile .

# 3. Toolbox (independent) — can run in parallel with cron
docker build -t ghcr.io/agento-cc/agento-toolbox:<VERSION> \
  -f docker/toolbox/Dockerfile .
```

Replace `<VERSION>` with the version from `pyproject.toml` (e.g., `0.2.5`).

These tagged images will be picked up automatically by `agento install` since the generated
`.env` contains `AGENTO_VERSION=<VERSION>` and `docker-compose.yml` references
`${AGENTO_VERSION}`. Docker resolves local images before pulling from the registry.

## Step 5: Prepare test directory

Clean or create a test directory for a fresh install simulation:

```bash
# If test dir exists with running containers, tear them down first
cd <TEST_DIR>/docker && docker compose down -v 2>/dev/null; cd -

# Remove and recreate
rm -rf <TEST_DIR>
mkdir -p <TEST_DIR>
```

Default test directory: `/Users/mklauza/Projects/test-agento1`
(or whatever the user specifies).

## Step 6: Notify user

Tell the user everything is ready and they can run `agento install` interactively
from the test directory:

```
cd <TEST_DIR> && agento install
```

Do NOT run `agento install` from Claude — it requires interactive TTY input
(project path, install mode, etc.) that cannot be provided via Bash tool.

## Step 7: Refresh an existing project (optional)

Use AskUserQuestion to ask: "Want to refresh an existing project with the test build? Provide the full path, or skip."

If the user provides a path:

1. Update `AGENTO_VERSION` in `<path>/docker/.env`:
```bash
sed -i '' 's/^AGENTO_VERSION=.*/AGENTO_VERSION=<VERSION>/' <path>/docker/.env
```

2. Copy refreshed `docker-compose.yml` from the agento source template:
```bash
cp src/agento/framework/cli/templates/docker-compose.yml <path>/docker/docker-compose.yml
```

3. Recreate containers using local images (no pull):
```bash
cd <path>/docker && docker compose up -d --force-recreate
```

**WARNING:** Do NOT use `agento upgrade` in the sibling project — it fetches from
PyPI/GHCR and will overwrite the locally built CLI and Docker images.
