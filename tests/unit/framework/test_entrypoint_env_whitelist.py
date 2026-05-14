"""Regression guard: every env var any `from_env()` classmethod under
`src/agento/framework/` reads must match the cron entrypoint's whitelist
regex.

The cron entrypoint persists docker env into `/opt/cron-agent/env` via a
prefix whitelist, because `su - agent` wipes the parent environment and the
framework boots as the agent user. Any var read by a `from_env()` that
isn't whitelisted silently falls back to its default — exactly the bug
class this test prevents from regressing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = REPO_ROOT / "src/agento/framework/docker/cron/entrypoint.sh"
FRAMEWORK_DIR = REPO_ROOT / "src/agento/framework"


def _whitelist_pattern() -> re.Pattern[str]:
    text = ENTRYPOINT.read_text()
    m = re.search(r"env \| grep -E '\^\(([^)]+)\)'", text)
    assert m, "could not find env whitelist line in entrypoint.sh"
    return re.compile(rf"^({m.group(1)})")


def _from_env_literals() -> dict[str, list[str]]:
    """{relative file path: [var names]} for every literal `NAME` passed to
    `os.environ.get("NAME", ...)` inside a `from_env` classmethod under
    `src/agento/framework/`."""
    out: dict[str, list[str]] = {}
    for py_file in FRAMEWORK_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "from_env":
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not (
                    isinstance(func, ast.Attribute)
                    and func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "environ"
                ):
                    continue
                if not call.args:
                    continue
                key = call.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    rel = py_file.relative_to(REPO_ROOT).as_posix()
                    out.setdefault(rel, []).append(key.value)
    return out


def test_framework_from_env_vars_pass_entrypoint_whitelist():
    pattern = _whitelist_pattern()
    by_file = _from_env_literals()
    assert by_file, "expected at least one from_env() in src/agento/framework/"
    violations: list[str] = []
    for rel, names in by_file.items():
        for name in names:
            if not pattern.match(f"{name}=anything"):
                violations.append(f"  {rel}: {name}")
    assert not violations, (
        "the following env vars are read by framework from_env() "
        "classmethods but are not whitelisted in cron entrypoint.sh — use "
        "the AGENTO_ prefix (or add to the entrypoint whitelist if it must "
        "follow an external convention):\n" + "\n".join(violations)
    )
