# agento doctor

Check system prerequisites and available installation modes.

## Usage

```bash
agento doctor
```

## Checks

| Tool | Required for |
|------|-------------|
| Python >= 3.11 | Always (CLI itself) |
| uv | Recommended package manager |
| Docker | Docker Compose mode |
| Docker Compose V2 | Docker Compose mode |
| Node.js | Local toolbox mode |
| npm | Local toolbox mode |
| MySQL | Validates connectivity if `CRONDB_*` env vars are set |

## Output

```
Agento Doctor

  Python               OK       Python 3.12.0
  uv                   OK       uv 0.5.2
  Docker               OK       Docker version 27.0.0
  Docker Compose       OK       Docker Compose version v2.29.0
  Node.js              OK       v22.5.0
  npm                  OK       10.8.0
  MySQL                OK       localhost:3306

  Available modes:
    Docker Compose        ready
    Local dev             ready (Node.js + external MySQL)
```

## Exit Code

- `0` — Python >= 3.11 is available
- `1` — Python requirement not met
