# agento init

> **Deprecated:** The `init` command has been replaced by [`agento install`](install.md), which provides an interactive wizard with automatic Docker setup, migrations, and agent provider configuration.

Scaffold a new agento project.

## Usage

```bash
agento init <project> [--no-example]
```

## Options

| Flag | Description |
|------|-------------|
| `<project>` | Project directory name (created in cwd) |
| `--no-example` | Skip example module |

## Output

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

## After init

```bash
cd my-project
agento up
agento setup:upgrade
```
