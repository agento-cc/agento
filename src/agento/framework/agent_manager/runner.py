from __future__ import annotations

import logging
import os
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

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
        self.pid_callback: Callable[[int], None] | None = None
        self.session_id_callback: Callable[[str], None] | None = None

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
    def _build_resume_command(self, session_id: str, model: str | None = None) -> list[str]:
        """Return the CLI command list for resuming a session."""
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

    def _try_parse_session_id(self, line: str) -> str | None:
        """Try to extract session_id from a single output line.

        Subclasses override to parse agent-specific formats.
        Called incrementally during process execution.
        """
        return None

    # -- process execution ----------------------------------------------------

    def _execute_process(self, cmd: list[str], env: dict) -> subprocess.CompletedProcess:
        """Execute a subprocess with incremental output reading.

        Reads stdout/stderr in threads so that:
        - session_id can be detected and reported via callback immediately
        - partial output is available on timeout (not lost with the process)
        """
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.working_dir,
            env=env,
        )

        if self.pid_callback:
            try:
                self.pid_callback(proc.pid)
            except Exception:
                self.logger.warning(f"PID callback failed for pid={proc.pid}")

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        session_id_found: str | None = None

        def _drain(stream, lines: list[str], parse_session: bool) -> None:
            nonlocal session_id_found
            for line in stream:
                lines.append(line)
                if parse_session and session_id_found is None:
                    sid = self._try_parse_session_id(line)
                    if sid:
                        session_id_found = sid
                        if self.session_id_callback:
                            try:
                                self.session_id_callback(sid)
                            except Exception:
                                self.logger.warning(f"session_id_callback failed for sid={sid}")

        stdout_thread = threading.Thread(
            target=_drain, args=(proc.stdout, stdout_lines, True), daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain, args=(proc.stderr, stderr_lines, True), daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            proc.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            timed_out = True

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)

        if timed_out:
            session_id = session_id_found or self._extract_session_id_from_partial(stdout, stderr)
            exc = subprocess.TimeoutExpired(
                cmd=cmd, timeout=self.timeout_seconds, output=stdout, stderr=stderr,
            )
            exc.session_id = session_id  # type: ignore[attr-defined]
            raise exc

        return subprocess.CompletedProcess(
            args=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr,
        )

    def _extract_session_id_from_partial(self, stdout: str, stderr: str) -> str | None:
        """Best-effort session_id extraction from partial output after timeout."""
        try:
            fake_proc = subprocess.CompletedProcess(
                args=[], returncode=1, stdout=stdout, stderr=stderr,
            )
            raw = self._extract_raw(fake_proc)
            result = self._parse_output(raw)
            return result.subtype
        except Exception:
            return None

    # -- shared setup ---------------------------------------------------------

    def _resolve_env_and_model(
        self, model: str | None,
    ) -> tuple[str, Token | None, dict[str, str], str | None]:
        """Shared setup: resolve token, read credentials, build env, resolve model."""
        active_path = self.credentials_path or resolve_active_token(
            self.config, self.agent_type,
        )
        if active_path is None:
            raise RuntimeError(
                f"No active token for agent_type={self.agent_type.value}. "
                f"Register tokens and run rotation first."
            )
        token = self._resolve_token(active_path)
        credentials = read_credentials(active_path)
        model = model or self.model_override
        env = {**os.environ, **self._build_env(credentials)}
        return active_path, token, env, model

    def _execute_and_parse(
        self, cmd: list[str], env: dict, token: Token | None, model: str | None,
    ) -> RunResult:
        """Execute command, parse output, stamp metadata, record usage."""
        self.logger.info(f"{self.agent_type.value}-cli cmd: {' '.join(cmd)}")

        proc = self._execute_process(cmd, env)
        self.logger.info(
            f"{self.agent_type.value}-cli rc={proc.returncode} "
            f"stdout={len(proc.stdout)}b stderr={len(proc.stderr)}b"
        )
        if proc.stderr:
            self.logger.debug(f"{self.agent_type.value}-cli stderr: {proc.stderr[:500]}")

        raw = self._extract_raw(proc)
        result = self._parse_output(raw)
        result.agent_type = self.agent_type.value
        result.model = result.model or model
        self._record_usage(token, result)

        if proc.returncode != 0:
            err = RuntimeError(
                f"{self.agent_type.value} exited with code {proc.returncode}: "
                f"{raw[:500]}"
            )
            err.session_id = result.subtype  # type: ignore[attr-defined]
            raise err
        return result

    # -- template methods -----------------------------------------------------

    def run(self, prompt: str, *, model: str | None = None) -> RunResult:
        if self.dry_run:
            self.logger.info(f"[DRY RUN] DISABLE_LLM is set, skipping {self.agent_type.value} run.")
            return RunResult(raw_output="[DRY RUN] skipped")

        _active_path, token, env, model = self._resolve_env_and_model(model)
        cmd = self._build_command(prompt, model=model)
        return self._execute_and_parse(cmd, env, token, model)

    def resume(self, session_id: str, *, model: str | None = None) -> RunResult:
        if self.dry_run:
            self.logger.info(f"[DRY RUN] DISABLE_LLM is set, skipping {self.agent_type.value} resume.")
            return RunResult(raw_output="[DRY RUN] skipped")

        _active_path, token, env, model = self._resolve_env_and_model(model)
        cmd = self._build_resume_command(session_id, model=model)
        return self._execute_and_parse(cmd, env, token, model)

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
