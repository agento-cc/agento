# agento dev bootstrap

Set up the development environment for framework contributors.

## Usage

```bash
agento dev bootstrap
```

## What it does

1. Checks prerequisites (Python >= 3.11, uv, Node.js, npm)
2. Runs `uv sync --group dev` — installs Python dependencies
3. Runs `npm install` in `src/agento/toolbox/` — installs Node.js dependencies

## Prerequisites

Must be run from the repo root (git clone).

## After bootstrap

```bash
uv run pytest -q                     # Run Python tests
cd src/agento/toolbox && npm test     # Run JS tests
agento toolbox start                  # Run toolbox locally
```
