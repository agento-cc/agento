from __future__ import annotations

import logging
import os
import subprocess
from abc import ABC, abstractmethod

from ..runner import RunResult
from .active import read_credentials, resolve_active_token
from .config import AgentManagerConfig
from .models import AgentProvider, Token
from .token_store import get_token_by_path
from .usage_store import record_usage


class TokenRunner(ABC):
    """Base runner that resolves the active token, executes the CLI, and records usage.

    Template Method pattern: subclasses provide agent_type, env building,
    command building, and output parsing.  The ``run()`` method orchestrates
    the full lifecycle.
    """

    def __init__(
        self,
        *,
        working_dir: str = "/workspace",
        logger: logging.Logger | None = None,
        dry_run: bool = False,
        config: AgentManagerConfig | None = None,
        timeout_seconds: int = 1200,
        model_override: str | None = None,
        credentials_path: str | None = None,
    ):
        self.working_dir = working_dir
        self.logger = logger or logging.getLogger(__name__)
        self.dry_run = dry_run
        self.config = config or AgentManagerConfig()
        self.timeout_seconds = timeout_seconds
        self.model_override = model_override
        self.credentials_path = credentials_path

    # -- abstract hooks -------------------------------------------------------

    @property
    @abstractmethod
    def agent_type(self) -> AgentProvider: ...

    @abstractmethod
    def _build_env(self, credentials: dict) -> dict[str, str]:
        """Return env-var overrides derived from the credentials JSON."""
        ...

    @abstractmethod
    def _build_command(self, prompt: str, model: str | None = None) -> list[str]:
        """Return the CLI command list. Appends --model when set."""
        ...

    @abstractmethod
    def _parse_output(self, raw: str) -> RunResult:
        """Parse raw CLI stdout into a RunResult."""
        ...

    def build_command(self, prompt: str, *, model: str | None = None) -> list[str]:
        """Public command builder — delegates to subclass ``_build_command``."""
        return self._build_command(prompt, model=model)

    def _extract_raw(self, proc: subprocess.CompletedProcess) -> str:
        """Extract the raw string to pass to ``_parse_output``.

        Default: prefer stdout, fall back to stderr.
        Subclasses may override to combine both (e.g. Codex puts stats on stderr).
        """
        return proc.stdout or proc.stderr

    # -- template method ------------------------------------------------------

    def run(self, prompt: str, *, model: str | None = None) -> RunResult:
        if self.dry_run:
            self.logger.info(f"[DRY RUN] DISABLE_LLM is set, skipping {self.agent_type.value} run.")
            return RunResult(raw_output="[DRY RUN] skipped")

        # 1. Resolve active token path + DB record
        active_path = self.credentials_path or resolve_active_token(
            self.config, self.agent_type,
        )
        if active_path is None:
            raise RuntimeError(
                f"No active token for agent_type={self.agent_type.value}. "
                f"Register tokens and run rotation first."
            )
        token = self._resolve_token(active_path)

        # 2. Read credentials
        credentials = read_credentials(active_path)

        # 3. Build env + command (model from scoped config via consumer)
        model = model or self.model_override
        env = {**os.environ, **self._build_env(credentials)}
        cmd = self._build_command(prompt, model=model)
        self.logger.info(f"{self.agent_type.value}-cli cmd: {' '.join(cmd)}")

        # 4. Execute
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.working_dir,
            env=env,
            timeout=self.timeout_seconds,
        )
        self.logger.info(
            f"{self.agent_type.value}-cli rc={proc.returncode} "
            f"stdout={len(proc.stdout)}b stderr={len(proc.stderr)}b"
        )
        if proc.stderr:
            self.logger.debug(f"{self.agent_type.value}-cli stderr: {proc.stderr[:500]}")

        raw = self._extract_raw(proc)

        # 5. Parse output
        result = self._parse_output(raw)

        # 6. Stamp execution metadata on result
        result.agent_type = self.agent_type.value
        result.model = result.model or model

        # 7. Record usage (best-effort)
        self._record_usage(token, result)

        if proc.returncode != 0:
            err = RuntimeError(
                f"{self.agent_type.value} exited with code {proc.returncode}: "
                f"{raw[:500]}"
            )
            err.session_id = result.subtype  # type: ignore[attr-defined]
            raise err
        return result

    def _get_db_connection(self):
        """Get a DB connection using DatabaseConfig. Best-effort, may raise."""
        from ..database_config import DatabaseConfig
        from ..db import get_connection

        return get_connection(DatabaseConfig.from_env_and_json())

    def _resolve_token(self, credentials_path: str) -> Token | None:
        """Look up the Token DB record for a credentials path. Best-effort."""
        try:
            conn = self._get_db_connection()
            try:
                return get_token_by_path(conn, credentials_path)
            finally:
                conn.close()
        except Exception:
            self.logger.exception("Failed to resolve token from DB (best-effort)")
            return None

    def _record_usage(self, token: Token | None, result: RunResult) -> None:
        """Best-effort usage recording — never raises."""
        if token is None:
            self.logger.warning("No token resolved, skipping usage recording")
            return
        try:
            conn = self._get_db_connection()
            try:
                tokens_used = (result.input_tokens or 0) + (result.output_tokens or 0)
                record_usage(
                    conn,
                    token_id=token.id,
                    tokens_used=tokens_used,
                    input_tokens=result.input_tokens or 0,
                    output_tokens=result.output_tokens or 0,
                    duration_ms=result.duration_ms or 0,
                    model=result.model,
                    logger=self.logger,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            self.logger.exception("Failed to record usage (best-effort, continuing)")
