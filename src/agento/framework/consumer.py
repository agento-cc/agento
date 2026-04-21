from __future__ import annotations

import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .agent_manager.models import AgentProvider
from .agent_manager.token_resolver import TokenResolver
from .agent_manager.token_store import get_primary_token
from .agent_view_runtime import resolve_agent_view_runtime
from .artifacts_dir import (
    build_artifacts_dir,
    copy_build_to_artifacts_dir,
    get_current_build_dir,
    prepare_artifacts_dir,
)
from .bootstrap import dispatch_shutdown, get_module_config
from .channels.registry import get_channel
from .consumer_config import ConsumerConfig
from .database_config import DatabaseConfig
from .db import get_connection
from .event_manager import get_event_manager
from .events import (
    AgentViewRunFinishedEvent,
    AgentViewRunStartedEvent,
    ConsumerStartedEvent,
    ConsumerStoppingEvent,
    JobClaimedEvent,
    JobDeadEvent,
    JobFailedEvent,
    JobRetryingEvent,
    JobSucceededEvent,
    WorkerStartedEvent,
    WorkerStoppedEvent,
)
from .job_models import Job, JobStatus
from .retry_policy import evaluate as evaluate_retry
from .runner import RunResult
from .runner_factory import create_runner
from .workflows import get_workflow_class
from .workflows.base import JobContext


@dataclass
class _JobResult:
    """Carries execution metadata from _run_job to _finalize_job."""
    summary: str
    agent_type: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt: str | None = None
    output: str | None = None
    session_id: str | None = None

    @classmethod
    def from_run_result(cls, result: RunResult, summary: str) -> _JobResult:
        return cls(
            summary=summary,
            agent_type=result.agent_type,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            prompt=result.prompt,
            output=result.raw_output,
            session_id=result.subtype,
        )

DEQUEUE_SQL = """
    SELECT * FROM job
    WHERE status = 'TODO'
      AND scheduled_after <= NOW()
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
"""

CLAIM_SQL = """
    UPDATE job
    SET status = 'RUNNING', started_at = NOW(), attempt = attempt + 1, updated_at = NOW()
    WHERE id = %s AND status = 'TODO'
"""


class Consumer:
    """Long-running consumer that dequeues and executes jobs from MySQL."""

    def __init__(
        self,
        db_config: DatabaseConfig,
        consumer_config: ConsumerConfig,
        logger: logging.Logger,
        *,
        model_override: str | None = None,
    ):
        self.logger = logger
        self.model_override = model_override
        self._shutdown = threading.Event()
        self._db_config = db_config
        self._consumer_config = consumer_config
        self._token_resolver = TokenResolver()

    def run(self) -> None:
        """Main loop. Blocks until SIGTERM/SIGINT."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        max_workers = self._consumer_config.max_workers
        self.logger.info(
            f"Consumer starting: max_workers={max_workers}, "
            f"poll_interval={self._consumer_config.poll_interval}s, "
            f"job_timeout={self._consumer_config.job_timeout_seconds}s"
        )

        get_event_manager().dispatch("consumer_start_after", ConsumerStartedEvent())

        self._recover_stale_jobs()

        semaphore = threading.Semaphore(max_workers)
        executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="consumer",
        )

        def _run_and_release(job: Job) -> None:
            try:
                self._execute_job(job)
            finally:
                semaphore.release()

        try:
            while not self._shutdown.is_set():
                if not semaphore.acquire(timeout=self._consumer_config.poll_interval):
                    continue  # timed out waiting for a free slot
                if self._shutdown.is_set():
                    semaphore.release()
                    break
                job = self._try_dequeue()
                if job:
                    executor.submit(_run_and_release, job)
                else:
                    semaphore.release()
                    self._shutdown.wait(timeout=self._consumer_config.poll_interval)
        finally:
            get_event_manager().dispatch("consumer_stop_before", ConsumerStoppingEvent())
            self.logger.info("Consumer shutting down, waiting for running jobs...")
            executor.shutdown(wait=True, cancel_futures=False)
            dispatch_shutdown()
            self.logger.info("Consumer stopped.")

    def _handle_signal(self, signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        self.logger.info(f"Received {sig_name}, initiating graceful shutdown")
        self._shutdown.set()

    def _save_pid(self, job_id: int, pid: int) -> None:
        """Best-effort: save subprocess PID to job row."""
        try:
            conn = get_connection(self._db_config)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE job SET pid = %s, updated_at = NOW() WHERE id = %s",
                        (pid, job_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            self.logger.warning(f"Failed to save PID {pid} for job {job_id} (best-effort)")

    def _save_session_id(self, job_id: int, session_id: str) -> None:
        """Best-effort: save session_id to job row."""
        try:
            conn = get_connection(self._db_config)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE job SET session_id = %s, updated_at = NOW() WHERE id = %s",
                        (session_id, job_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            self.logger.warning(f"Failed to save session_id for job {job_id} (best-effort)")

    @staticmethod
    def _is_pid_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _recover_stale_jobs(self) -> None:
        """Recover RUNNING jobs whose process has died (PID-based check).

        Jobs with a PID are checked via os.kill(pid, 0).  Jobs without a PID
        (callback hasn't fired yet) fall back to the timestamp threshold so we
        don't kill freshly-claimed jobs in multi-worker mode.
        """
        threshold = self._consumer_config.job_timeout_seconds + 60
        try:
            conn = get_connection(self._db_config)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, reference_id, pid, attempt, max_attempts, started_at "
                        "FROM job WHERE status = 'RUNNING'"
                    )
                    running_jobs = cur.fetchall()

                    retried = 0
                    dead = 0
                    for row in running_jobs:
                        job_id = row["id"]
                        ref_id = row["reference_id"]
                        pid = row["pid"]
                        attempt = row["attempt"]
                        max_attempts = row["max_attempts"]

                        if pid is not None:
                            if self._is_pid_alive(int(pid)):
                                continue
                        else:
                            # No PID yet — fall back to timestamp guard
                            started_at = row["started_at"]
                            if started_at is None:
                                continue
                            # PyMySQL returns naive datetimes (UTC assumed)
                            now = datetime.now(UTC).replace(tzinfo=None)
                            elapsed = (now - started_at).total_seconds()
                            if elapsed < threshold:
                                continue

                        if attempt < max_attempts:
                            cur.execute(
                                """
                                UPDATE job
                                SET status = 'TODO', finished_at = NOW(),
                                    error_message = %s,
                                    error_class = 'StaleJobRecovery',
                                    scheduled_after = NOW(), updated_at = NOW()
                                WHERE id = %s AND status = 'RUNNING'
                                """,
                                (f"Recovered: process dead (pid={pid})", job_id),
                            )
                            retried += 1
                            self.logger.warning(
                                f"Recovered stale job -> TODO (retry) | "
                                f"job_id={job_id} reference_id={ref_id} "
                                f"pid={pid} attempt={attempt}/{max_attempts}"
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE job
                                SET status = 'DEAD', finished_at = NOW(),
                                    error_message = %s,
                                    error_class = 'StaleJobRecovery',
                                    updated_at = NOW()
                                WHERE id = %s AND status = 'RUNNING'
                                """,
                                (f"Recovered: process dead (pid={pid}), max attempts reached", job_id),
                            )
                            dead += 1
                            self.logger.warning(
                                f"Recovered stale job -> DEAD | "
                                f"job_id={job_id} reference_id={ref_id} "
                                f"pid={pid} attempt={attempt}/{max_attempts}"
                            )

                conn.commit()
                if retried or dead:
                    self.logger.warning(
                        f"Stale job recovery: {retried} retried, {dead} dead-lettered"
                    )
            finally:
                conn.close()
        except Exception:
            self.logger.exception("Failed to recover stale jobs (non-fatal, continuing)")

    def _try_dequeue(self) -> Job | None:
        """Claim one job from the queue. Returns None if empty."""
        conn = get_connection(self._db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(DEQUEUE_SQL)
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None

                job = Job.from_row(row)
                cur.execute(CLAIM_SQL, (job.id,))
                conn.commit()

                job.status = JobStatus.RUNNING
                job.attempt += 1

                get_event_manager().dispatch("job_claim_after", JobClaimedEvent(job=job))

                return job
        except Exception:
            conn.rollback()
            self.logger.exception("Error during dequeue")
            return None
        finally:
            conn.close()

    def _execute_job(self, job: Job) -> None:
        """Execute a single job. Runs in a thread pool thread."""
        worker_slot = threading.current_thread().name
        em = get_event_manager()

        self.logger.info(
            "Starting job",
            extra={
                "job_id": job.id,
                "type": job.type.value,
                "reference_id": job.reference_id,
                "attempt": job.attempt,
                "agent_view_id": job.agent_view_id,
                "priority": job.priority,
                "worker_slot": worker_slot,
            },
        )
        em.dispatch("worker_start_after", WorkerStartedEvent(
            worker_slot=worker_slot, job_id=job.id,
        ))

        start_time = time.monotonic()
        error: Exception | None = None
        job_result: _JobResult | None = None

        try:
            job_result = self._run_job(job)
        except Exception as exc:
            error = exc
            self.logger.exception(
                "Job failed",
                extra={
                    "job_id": job.id, "reference_id": job.reference_id,
                    "attempt": job.attempt, "worker_slot": worker_slot,
                },
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        self._finalize_job(job, error, job_result, elapsed_ms)

        em.dispatch("worker_stop_after", WorkerStoppedEvent(
            worker_slot=worker_slot, job_id=job.id, elapsed_ms=elapsed_ms,
        ))

    def _run_job(self, job: Job) -> _JobResult:
        """Dispatch to the appropriate workflow with agent_view routing."""
        channel = get_channel(job.source)
        em = get_event_manager()
        artifacts_dir = None

        # Resolve agent_view runtime profile (provider, model, scoped config)
        conn = get_connection(self._db_config)
        try:
            runtime = resolve_agent_view_runtime(conn, job.agent_view_id)

            # Determine provider and model: agent_view config > CLI override > primary token
            if runtime.provider is not None:
                agent_type = AgentProvider(runtime.provider)
                model_override = runtime.model or self.model_override
            else:
                # Fallback: infer provider from primary token (backward compat)
                primary = get_primary_token(conn)
                if primary is None:
                    raise RuntimeError(
                        "No agent_view/provider configured and no primary token set. "
                        "Run: bin/agento config:set agent_view/provider claude"
                    )
                agent_type = primary.agent_type
                model_override = self.model_override

            # Resolve token via TokenResolver
            token = self._token_resolver.resolve(conn, agent_type)

            # Resolve shared toolbox base URL (needed below for writer injection).
            from .scoped_config import get_module_config as _scoped_get_module_config
            core_cfg = _scoped_get_module_config(conn, "core") or {}
            toolbox_url = core_cfg.get("toolbox/url") or "http://toolbox:3001"
        finally:
            conn.close()

        # Per-job artifacts directory (only when agent_view is set)
        current_build = None
        if runtime.agent_view is not None and runtime.workspace is not None:
            artifacts_dir = build_artifacts_dir(
                runtime.workspace.code, runtime.agent_view.code, job.id,
            )
            prepare_artifacts_dir(artifacts_dir)

            current_build = get_current_build_dir(
                runtime.workspace.code, runtime.agent_view.code,
            )
            if current_build is not None:
                copy_build_to_artifacts_dir(
                    current_build, artifacts_dir,
                    job_id=job.id,
                    provider=runtime.provider,
                )
            elif runtime.provider:
                from .config_writer import get_agent_config, get_config_writer
                agent_config = get_agent_config(runtime.scoped_overrides)
                writer = get_config_writer(runtime.provider)
                writer.prepare_workspace(
                    artifacts_dir, agent_config,
                    agent_view_id=job.agent_view_id,
                    toolbox_url=toolbox_url,
                )

        em.dispatch("agent_view_run_start_before", AgentViewRunStartedEvent(
            job=job,
            agent_view_id=job.agent_view_id,
            provider=agent_type.value,
            model=model_override,
            priority=job.priority,
            artifacts_dir=str(artifacts_dir) if artifacts_dir else "",
        ))

        success = True
        try:
            runner = create_runner(
                agent_type,
                logger=self.logger,
                dry_run=self._consumer_config.disable_llm,
                timeout_seconds=self._consumer_config.job_timeout_seconds,
                model_override=model_override,
                working_dir=str(artifacts_dir) if artifacts_dir else None,
                home_dir=str(current_build) if current_build else None,
                credentials_override=token.credentials,
            )
            runner.pid_callback = lambda pid: self._save_pid(job.id, pid)
            runner.session_id_callback = lambda sid: self._save_session_id(job.id, sid)

            # Resume instead of fresh run if previous attempt left a session_id
            should_resume = (
                job.attempt > 1
                and job.session_id is not None
                and not self._is_pid_alive(job.pid)
            )
            if should_resume:
                self.logger.info(
                    f"Resuming session {job.session_id} for job {job.id} "
                    f"(attempt={job.attempt}, prev_pid={job.pid})"
                )
                result = runner.resume(job.session_id, model=model_override)
                result.prompt = f"[RESUME] session_id={job.session_id}"
                summary = f"resumed session_id={job.session_id} {result.stats_line}"
                return _JobResult.from_run_result(result, summary)

            workflow = get_workflow_class(job.type)(runner, self.logger)

            module_config = get_module_config(job.source) if job.source != "blank" else {}
            context = JobContext(
                config=module_config,
                logger=self.logger,
                update_reference_id=self._update_job_reference_id,
            )
            result = workflow.execute_job(channel, job, context)

            summary = (
                result.raw_output
                if result.input_tokens is None and result.raw_output
                else f"subtype={result.subtype or '?'} {result.stats_line}"
            )
            return _JobResult.from_run_result(result, summary)
        except Exception:
            success = False
            raise
        finally:
            em.dispatch("agent_view_run_finish_after", AgentViewRunFinishedEvent(
                job=job,
                agent_view_id=job.agent_view_id,
                provider=agent_type.value,
                model=model_override,
                success=success,
            ))

    def _update_job_reference_id(self, job_id: int, reference_id: str) -> None:
        conn = get_connection(self._db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job SET reference_id = %s, updated_at = NOW() WHERE id = %s",
                    (reference_id, job_id),
                )
            conn.commit()
        finally:
            conn.close()

    def _finalize_job(
        self,
        job: Job,
        error: Exception | None,
        job_result: _JobResult | None,
        elapsed_ms: int,
    ) -> None:
        """Update job status in MySQL after execution completes.

        Retries DB updates up to 3 times with fresh connections to avoid
        leaving jobs stuck in RUNNING if the DB hiccups.
        """
        max_db_retries = 3
        em = get_event_manager()

        for db_attempt in range(1, max_db_retries + 1):
            conn = get_connection(self._db_config)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT status FROM job WHERE id = %s", (job.id,))
                    row = cur.fetchone()
                if row is None:
                    current_status = None
                elif isinstance(row, dict):
                    current_status = row.get("status")
                else:
                    current_status = row[0]
                if current_status != "RUNNING":
                    self.logger.info(
                        "Job finalize skipped (status changed during run)",
                        extra={
                            "job_id": job.id,
                            "reference_id": job.reference_id,
                            "current_status": current_status,
                        },
                    )
                    return

                if error is None:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE job
                            SET status = 'SUCCESS', finished_at = NOW(),
                                result_summary = %s, agent_type = %s, model = %s,
                                input_tokens = %s, output_tokens = %s,
                                prompt = %s, output = %s,
                                updated_at = NOW()
                            WHERE id = %s AND status = 'RUNNING'
                            """,
                            (
                                job_result.summary if job_result else None,
                                job_result.agent_type if job_result else None,
                                job_result.model if job_result else None,
                                job_result.input_tokens if job_result else None,
                                job_result.output_tokens if job_result else None,
                                job_result.prompt if job_result else None,
                                job_result.output if job_result else None,
                                job.id,
                            ),
                        )
                    conn.commit()
                    self.logger.info(
                        "Job succeeded",
                        extra={
                            "job_id": job.id,
                            "reference_id": job.reference_id,
                            "status": "SUCCESS",
                            "duration_ms": elapsed_ms,
                            "result_summary": job_result.summary if job_result else None,
                        },
                    )
                    em.dispatch(
                        "job_succeed_after",
                        JobSucceededEvent(
                            job=job,
                            summary=job_result.summary if job_result else None,
                            agent_type=job_result.agent_type if job_result else None,
                            model=job_result.model if job_result else None,
                            elapsed_ms=elapsed_ms,
                        ),
                    )
                else:
                    error_class = error.__class__.__name__
                    error_msg = str(error)[:2000]
                    decision = evaluate_retry(error_class, job.attempt, job.max_attempts)

                    em.dispatch(
                        "job_fail_after",
                        JobFailedEvent(job=job, error=error, elapsed_ms=elapsed_ms),
                    )

                    # Extract session_id from result or error (best-effort)
                    session_id = job_result.session_id if job_result else None
                    if session_id is None:
                        session_id = getattr(error, "session_id", None)

                    if decision.should_retry:
                        scheduled_after = datetime.now(UTC) + timedelta(seconds=decision.delay_seconds)
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE job
                                SET status = 'TODO', finished_at = NOW(),
                                    error_message = %s, error_class = %s,
                                    session_id = COALESCE(%s, session_id),
                                    scheduled_after = %s, updated_at = NOW()
                                WHERE id = %s AND status = 'RUNNING'
                                """,
                                (error_msg, error_class, session_id, scheduled_after, job.id),
                            )
                        conn.commit()
                        self.logger.info(
                            f"Job scheduled for retry: {decision.reason}",
                            extra={
                                "job_id": job.id,
                                "reference_id": job.reference_id,
                                "status": "TODO",
                                "duration_ms": elapsed_ms,
                            },
                        )
                        em.dispatch(
                            "job_retry_after",
                            JobRetryingEvent(
                                job=job,
                                error=error,
                                delay_seconds=decision.delay_seconds,
                                elapsed_ms=elapsed_ms,
                            ),
                        )
                    else:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE job
                                SET status = 'DEAD', finished_at = NOW(),
                                    error_message = %s, error_class = %s,
                                    session_id = COALESCE(%s, session_id),
                                    updated_at = NOW()
                                WHERE id = %s AND status = 'RUNNING'
                                """,
                                (error_msg, error_class, session_id, job.id),
                            )
                        conn.commit()
                        self.logger.warning(
                            f"Job dead-lettered: {decision.reason}",
                            extra={
                                "job_id": job.id,
                                "reference_id": job.reference_id,
                                "status": "DEAD",
                                "duration_ms": elapsed_ms,
                            },
                        )
                        em.dispatch(
                            "job_dead_after",
                            JobDeadEvent(job=job, error=error, elapsed_ms=elapsed_ms),
                        )
                return  # DB update succeeded
            except Exception:
                conn.rollback()
                if db_attempt < max_db_retries:
                    self.logger.warning(
                        f"Failed to finalize job {job.id} "
                        f"(DB attempt {db_attempt}/{max_db_retries}), retrying..."
                    )
                    time.sleep(1)
                else:
                    self.logger.critical(
                        f"FAILED to finalize job {job.id} after {max_db_retries} attempts. "
                        f"Job may be stuck in RUNNING. Manual intervention required."
                    )
            finally:
                conn.close()
