# agento init

Scaffold a new agento project.

## Usage

```bash
agento init <project> [--local] [--no-example]
```

## Options

| Flag | Description |
|------|-------------|
| `<project>` | Project directory name (created in cwd) |
| `--local` | Local dev mode — no Docker directory, generates `.env` with MySQL connection placeholders |
| `--no-example` | Skip example module |

## Default mode (Docker Compose)

Creates a project ready for `agento up`:

```
my-project/
    .agento/project.json
    app/code/
    workspace/systems/
    workspace/tmp/
    logs/
    tokens/
    storage/
    docker/
        docker-compose.yml
        .env
    secrets.env.example
    .gitignore
```

## Local mode (`--local`)

Creates a project for local development with external MySQL:

```
my-project/
    .agento/project.json
    app/code/
    workspace/systems/
    workspace/tmp/
    logs/
    tokens/
    storage/
    .env                    # MySQL connection placeholders
    secrets.env.example
    .gitignore
```

## After init

**Docker Compose:**
```bash
cd my-project
agento up
agento setup:upgrade
```

**Local dev:**
```bash
cd my-project
# Edit .env with MySQL connection details
agento doctor
agento setup:upgrade
agento toolbox start
```
