# `agento run` — Run the configured agent CLI

Spawns the agent CLI inside the `sandbox` container, with `HOME` and the working directory set to the agent_view's materialized workspace build. Credentials, SSH key, instructions, and skills are all resolved naturally from that HOME. The exact CLI command is built by the provider's registered `CliInvoker` — no provider-specific logic lives in the `run` command itself.

Two modes are selected automatically by presence of a prompt argument:

| Invocation | Mode | Semantics |
|---|---|---|
| `agento run <code>` | **Interactive** | Opens a TTY session inside the sandbox (`docker exec -it`). Signals, paste, arrow keys work as if the CLI were local. |
| `agento run <code> "<prompt>"` | **Headless (one-shot)** | Runs the agent with the given prompt, streams output to your terminal, then exits with the agent's exit code (`docker exec -T`). Stdin is closed. |

Shortcut: `ru`.

## Usage

### Interactive

```bash
agento run dev_01       # Opens the configured agent CLI for agent_view 'dev_01'
agento run qa_01        # Same, for a different agent_view
```

### Headless (one-shot)

```bash
agento run dev_01 "what MCP tools and skills do you have?"
agento run dev_01 "refactor src/foo.py to use dataclasses"
```

Everything after the agent_view code is treated as a single prompt string (via `argparse.REMAINDER`). Multi-word prompts do not need extra quoting beyond the shell's usual rules.

**Example headless session:**

```
$ agento run dev_01 "jakie masz toole z mcp i skille?"
OpenAI Codex v0.121.0 (research preview)
--------
workdir: /workspace/build/it/dev_01/builds/51
model: gpt-5.4
provider: openai
approval: never
sandbox: danger-full-access
session id: 019dab1e-73c3-7392-86c2-67ccd693a161
--------
user
jakie masz toole z mcp i skille?
codex
Mam w tej sesji dostęp do tych grup narzędzi MCP i skilli.
...
```

Exit code of the agent CLI is propagated to the shell, so headless mode composes naturally with scripts, CI, and `make`.

## What It Does

1. Calls `docker compose exec -T cron agento agent_view:runtime <code>` to resolve the runtime profile. When a prompt is provided, the host passes `--prompt <prompt>` so the cron container can also return the provider-specific **headless command**. The command is built by the `CliInvoker` the agent module registered in `di.json` — the host code itself is agent-agnostic.
2. Validates that a build exists on the host at `workspace/build/<workspace>/<agent_view>/current/`.
3. Executes the returned command inside `sandbox`:
   - **Interactive:** `os.execvp("docker", ["compose", "-f", …, "exec", "-it", "-e", "HOME=…", "-e", "TERM=…", "-w", …, "sandbox", *interactive_command])` — replaces the current process so the TTY transfer is clean.
   - **Headless:** `subprocess.run(["docker", "compose", "-f", …, "exec", "-T", "-e", "HOME=…", "-w", …, "sandbox", *headless_command], stdin=subprocess.DEVNULL)` — waits for completion and propagates the exit code.

## Agent-Agnostic Architecture

`agento run` never branches on a provider name. Support for a new agent (OpenCode, Hermes, …) requires **zero edits to the framework** — the agent module ships a `CliInvoker` and declares it in its `di.json`:

```json
{
  "cli_invokers": [
    {"provider": "myagent", "class": "src.cli.MyAgentCliInvoker"}
  ]
}
```

The invoker implements two methods:

```python
class MyAgentCliInvoker:
    def interactive_command(self) -> list[str]:
        return ["myagent"]

    def headless_command(self, prompt: str, *, model: str | None = None) -> list[str]:
        cmd = ["myagent", "run", "--prompt", prompt]
        if model:
            cmd += ["--model", model]
        return cmd
```

Framework protocol lives in [`src/agento/framework/cli_invoker.py`](../../src/agento/framework/cli_invoker.py); shipped implementations: [`claude/src/cli.py`](../../src/agento/modules/claude/src/cli.py), [`codex/src/cli.py`](../../src/agento/modules/codex/src/cli.py).

## Preconditions

- Containers running: `agento up` (or `cd docker && docker compose -f docker-compose.dev.yml up -d`).
- `agent_view/provider` configured:
  ```bash
  agento config:set agent_view/provider claude --agent-view dev_01
  ```
- Workspace build exists (tokens + SSH key materialized):
  ```bash
  agento workspace:build --agent-view dev_01
  ```

## Errors

| Message | Fix |
|---|---|
| `agent_view 'xyz' not found` | Check `agento config:list agent_view` and the `agent_view` table. |
| `no provider configured` | `agento config:set agent_view/provider <provider> --agent-view <code>` |
| `provider 'X' has no CliInvoker registered` | The agent module for `X` must declare a `cli_invokers` entry in `di.json`. Built-in providers: `claude`, `codex`. |
| `no build found` | `agento workspace:build --agent-view <code>` |
| docker exec error | Start containers: `agento up`. |

## Inspection

If you want to see the resolved runtime (including the CLI command the framework would run) without spawning the sandbox:

```bash
agento agent_view:runtime dev_01
# → {"agent_view_id": 2, "agent_view_code": "dev_01",
#    "workspace_id": 1, "workspace_code": "it",
#    "provider": "claude", "model": "claude-opus-4-6",
#    "home": "/workspace/build/it/dev_01/current",
#    "interactive_command": ["claude"],
#    "headless_command": null}

# Ask for the headless command too by passing a prompt:
agento agent_view:runtime dev_01 --prompt "hello"
# → {..., "headless_command": ["claude", "-p", "hello",
#      "--dangerously-skip-permissions", "--output-format", "stream-json",
#      "--verbose", "--model", "claude-opus-4-6"]}

# Override the model ad-hoc (doesn't persist to DB):
agento agent_view:runtime dev_01 --prompt "hello" --model claude-sonnet-4-6
```

## Related

- [workspace-build.md](workspace-build.md) — how the build directory is materialized
- [../config/identity.md](../config/identity.md) — how SSH keys and tokens are stored per agent_view
- [../architecture/events.md](../architecture/events.md) — framework extensibility model (CliInvoker follows the same di.json pattern as ConfigWriter, Runner, AuthStrategy)
