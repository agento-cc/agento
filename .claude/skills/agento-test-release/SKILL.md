---
name: agento-test-release
description: Build and locally install Agento for testing. Use this skill when the user wants to test a release locally, try the built package, do a test install, or says things like "test release", "test install", "build and install locally", "try the package". Even just "test build" should trigger this skill.
---

# Test Release Workflow

Build Agento and install it locally via `uv tool install` for manual testing before a real release.

## Step 1: Build the package

```bash
uv build
```

This produces `.whl` and `.tar.gz` files in `dist/`.

## Step 2: Find the latest wheel

List `dist/` sorted by modification time and pick the newest `.whl` file:

```bash
ls -t dist/*.whl | head -1
```

## Step 3: Install locally

Install the wheel using `uv tool install` with `--force` to replace any previous installation:

```bash
uv tool install --force dist/<latest>.whl
```

## Step 4: Verify

Confirm the installed version:

```bash
agento --version
```

Report the installed version to the user.
