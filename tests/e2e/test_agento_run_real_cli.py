"""End-to-end happy path for every token type via ``agento run``.

For each registered token type we drive the REAL pipeline:
- force the token under test to win pool selection by giving it the lowest
  priority (``token:set-priority``; lower wins),
- point the agent_view at the matching provider and a cheap model via scoped
  config (``config:set agent_view/provider`` + ``agent_view/model``),
- run ``agento run <agent_view> "<prompt>"`` which shells into the Docker
  sandbox, materializes the token's credentials, and invokes the real agent CLI,
- assert the run exits 0 (auth + model + execution all worked).

Marked ``@pytest.mark.e2e`` because they invoke the real Docker stack and the
real provider APIs (real money). They are gated behind an explicit opt-in
because they also TEMPORARILY MUTATE the deployment DB (one token's priority and
the agent_view's provider/model), restored in a ``finally`` block:

    AGENTO_E2E=1 AGENTO_E2E_AGENT_VIEW=<code> bin/test

Teardown captures the agent_view-scoped provider/model overrides BEFORE the run
and restores them afterwards — setting them back if they existed, or removing
them only if they were unset — so pre-existing config for AGENTO_E2E_AGENT_VIEW
is preserved, not erased.

All DB/run interaction goes through the ``agento`` CLI (which proxies into the
containers); the deployment DB is not reachable directly from the host.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parents[2]
_AGENTO = shutil.which("agento") or str(_PROJECT_ROOT / "bin" / "agento")
_E2E_ENABLED = os.environ.get("AGENTO_E2E") == "1"
_AGENT_VIEW = os.environ.get("AGENTO_E2E_AGENT_VIEW")

# Cheap model per provider — keeps the real run inexpensive.
_MODEL_BY_PROVIDER = {"claude": "haiku", "codex": "gpt-5.4-mini"}

# (provider, token type) — one happy-path run per registered type. A type with
# no healthy token registered is skipped individually.
_TOKEN_MATRIX = [
    ("claude", "oauth"),
    ("claude", "anthropic_api_key"),
    ("codex", "oauth"),
    ("codex", "openai_api_key"),
    ("codex", "codex_access_token"),
]

# Far below any real priority so the chosen token deterministically wins
# selection (ORDER BY priority ASC) regardless of the others.
_FORCE_PRIORITY = -1_000_000

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _E2E_ENABLED,
        reason="set AGENTO_E2E=1 to run (spends real provider tokens, mutates the pool)",
    ),
    pytest.mark.skipif(
        not _AGENT_VIEW,
        reason="set AGENTO_E2E_AGENT_VIEW=<code> to choose the agent_view to run",
    ),
]


def _agento(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_AGENTO, *args],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _agento_ok(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    res = _agento(args, timeout=timeout)
    assert res.returncode == 0, f"`agento {' '.join(args)}` failed: {res.stderr[:600]}"
    return res


def _healthy_tokens() -> list[dict]:
    res = _agento(["token:list", "--json"])
    if res.returncode != 0:
        pytest.skip(f"`agento token:list` failed (is the stack up?): {res.stderr[:300]}")
    tokens = json.loads(res.stdout)
    return [t for t in tokens if t.get("status") == "ok" and t.get("enabled", True)]


def _agent_view_override(path: str) -> str | None:
    """Return the value of ``path`` set at THIS agent_view's scope, or None when
    no agent_view-scoped override exists (unset, or the value is shared with
    another scope — in which case removing it leaves the effective value
    unchanged). ``config:get`` prints per-scope lines tagged like
    ``[agent_view: <code>]``; a deduplicated single line (all scopes equal)
    carries no tag and safely maps to None."""
    res = _agento(["config:get", path])
    tag = f"[agent_view: {_AGENT_VIEW}]"
    for line in res.stdout.splitlines():
        if tag in line and " = " in line:
            return line.split(" = ", 1)[1].rsplit("  [", 1)[0].strip()
    return None


def _restore_override(path: str, prior: str | None) -> None:
    if prior is not None:
        _agento(["config:set", path, prior, "--agent-view", _AGENT_VIEW])
    else:
        _agento(["config:remove", path, "--agent-view", _AGENT_VIEW])


@pytest.mark.parametrize(
    ("provider", "token_type"),
    _TOKEN_MATRIX,
    ids=[f"{p}-{t}" for p, t in _TOKEN_MATRIX],
)
def test_agento_run_happy_path_per_token_type(provider: str, token_type: str):
    candidates = [
        t for t in _healthy_tokens()
        if t["agent_type"] == provider and t["type"] == token_type
    ]
    if not candidates:
        pytest.skip(f"no healthy {provider}/{token_type} token registered")
    token = candidates[0]
    model = _MODEL_BY_PROVIDER[provider]
    old_priority = token["priority"]
    prior_provider = _agent_view_override("agent_view/provider")
    prior_model = _agent_view_override("agent_view/model")

    try:
        # Steer the run: matching provider + cheap model (scoped config), and
        # force this exact token to win pool selection.
        _agento_ok(["config:set", "agent_view/provider", provider, "--agent-view", _AGENT_VIEW])
        _agento_ok(["config:set", "agent_view/model", model, "--agent-view", _AGENT_VIEW])
        _agento_ok(["token:set-priority", str(token["id"]), str(_FORCE_PRIORITY)])

        run = _agento(
            ["run", _AGENT_VIEW, "Reply with exactly the word: pong"],
            timeout=300,
        )
        assert run.returncode == 0, (
            f"`agento run` failed for {provider}/{token_type} (model={model}): "
            f"rc={run.returncode}\nstderr={run.stderr[:800]}"
        )
        assert run.stdout.strip(), "agent produced no output"
    finally:
        # Restore exactly what we changed (best-effort): token priority and the
        # agent_view-scoped provider/model overrides (set back if they existed,
        # remove only if they were unset).
        _agento(["token:set-priority", str(token["id"]), str(old_priority)])
        _restore_override("agent_view/model", prior_model)
        _restore_override("agent_view/provider", prior_provider)
