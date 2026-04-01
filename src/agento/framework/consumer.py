from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .agent_config_writer import populate_agent_configs
from .agent_manager.models import AgentProvider
from .agent_manager.token_resolver import TokenResolver
from .agent_manager.token_store import get_primary_token
from .agent_view_runtime import resolve_agent_view_runtime
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
from .run_dir import build_run_dir, cleanup_run_dir, prepare_run_dir
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

        get_event_manager().dispatch("consumer_started", ConsumerStartedEvent())

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
            get_event_manager().dispatch("consumer_stopping", ConsumerStoppingEvent())
            self.logger.info("Consumer shutting down, waiting for running jobs...")
            executor.shutdown(wait=True, cancel_futures=False)
            dispatch_shutdown()
            self.logger.info("Consumer stopped.")

    def _handle_signal(self, signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        self.logger.info(f"Received {sig_name}, initiating graceful shutdown")
        self._shutdown.set()

    def _recover_stale_jobs(self) -> None:
        """Reset RUNNING jobs orphaned by previous consumer crashes."""
        threshold = self._consumer_config.job_timeout_seconds + 60
        try:
            conn = get_connection(self._db_config)
            try:
                with conn.cursor() as cur:
                    # Retry-eligible jobs → TODO
                    cur.execute(
                        """
                        UPDATE job
                        SET status = 'TODO', finished_at = NOW(),
                            error_message = 'Recovered stale job: process died or timed out',
                            error_class = 'StaleJobRecovery',
                            scheduled_after = NOW(), updated_at = NOW()
                        WHERE status = 'RUNNING'
                          AND started_at < NOW() - INTERVAL %s SECOND
                          AND attempt < max_attempts
                        """,
                        (threshold,),
                    )
                    retried = cur.rowcount

                    # Exhausted jobs → DEAD
                    cur.execute(
                        """
                        UPDATE job
                        SET status = 'DEAD', finished_at = NOW(),
                            error_message = 'Recovered stale job: max attempts reached',
                            error_class = 'StaleJobRecovery',
                            updated_at = NOW()
                        WHERE status = 'RUNNING'
                          AND started_at < NOW() - INTERVAL %s SECOND
                          AND attempt >= max_attempts
                        """,
                        (threshold,),
                    )
                    dead = cur.rowcount

                conn.commit()
                if retried or dead:
                    self.logger.warning(
                        f"Recovered stale jobs: {retried} retried, {dead} dead-lettered "
                        f"(threshold={threshold}s)"
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

                get_event_manager().dispatch("job_claimed", JobClaimedEvent(job=job))

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
        em.dispatch("agento_worker_started", WorkerStartedEvent(
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

        em.dispatch("agento_worker_stopped", WorkerStoppedEvent(
            worker_slot=worker_slot, job_id=job.id, elapsed_ms=elapsed_ms,
        ))

    def _run_job(self, job: Job) -> _JobResult:
        """Dispatch to the appropriate workflow with agent_view routing."""
        channel = get_channel(job.source)
        em = get_event_manager()
        run_dir = None

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
                        "No agent/provider configured and no primary token set. "
                        "Run: bin/agento config:set agent/provider claude"
                    )
                agent_type = primary.agent_type
                model_override = self.model_override

            # Resolve token via TokenResolver
            token = self._token_resolver.resolve(conn, agent_type)
        finally:
            conn.close()

        # Per-run isolated directory (only when agent_view is set)
        if runtime.agent_view is not None and runtime.workspace is not None:
            run_dir = build_run_dir(
                runtime.workspace.code, runtime.agent_view.code, job.id,
            )
            prepare_run_dir(run_dir)
            populate_agent_configs(
                run_dir, runtime.scoped_overrides,
                agent_view_id=job.agent_view_id,
            )

        em.dispatch("agento_agent_view_run_started", AgentViewRunStartedEvent(
            job=job,
            agent_view_id=job.agent_view_id,
            provider=agent_type.value,
            model=model_override,
            priority=job.priority,
            run_dir=str(run_dir) if run_dir else "",
        ))

        success = True
        try:
            runner = create_runner(
                agent_type,
                logger=self.logger,
                dry_run=self._consumer_config.disable_llm,
                timeout_seconds=self._consumer_config.job_timeout_seconds,
                model_override=model_override,
                working_dir=str(run_dir) if run_dir else None,
                credentials_path=token.credentials_path,
            )
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
            em.dispatch("agento_agent_view_run_finished", AgentViewRunFinishedEvent(
                job=job,
                agent_view_id=job.agent_view_id,
                provider=agent_type.value,
                model=model_override,
                success=success,
            ))
            if run_dir is not None:
                cleanup_run_dir(run_dir)

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
                            WHERE id = %s
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
                        "job_succeeded",
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
                        "job_failed",
                        JobFailedEvent(job=job, error=error, elapsed_ms=elapsed_ms),
                    )

                    if decision.should_retry:
                        scheduled_after = datetime.now(UTC) + timedelta(seconds=decision.delay_seconds)
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE job
                                SET status = 'TODO', finished_at = NOW(),
                                    error_message = %s, error_class = %s,
                                    scheduled_after = %s, updated_at = NOW()
                                WHERE id = %s
                                """,
                                (error_msg, error_class, scheduled_after, job.id),
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
                            "job_retrying",
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
                                    error_message = %s, error_class = %s, updated_at = NOW()
                                WHERE id = %s
                                """,
                                (error_msg, error_class, job.id),
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
                            "job_dead",
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
