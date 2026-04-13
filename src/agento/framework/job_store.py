"""Job store — DB helpers for job lifecycle transitions."""
from __future__ import annotations

import os
import signal
import time

from .job_models import Job, JobStatus


def fetch_job(conn, job_id: int) -> Job | None:
    """Fetch a single job by ID. Returns None if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM job WHERE id = %s", (job_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return Job.from_row(row)


def pause_job(conn, job_id: int) -> Job:
    """Transition a RUNNING job to PAUSED. Sends SIGTERM to the subprocess if alive.

    Returns the updated Job.
    Raises ValueError if job is not found or not in RUNNING status.
    """
    job = fetch_job(conn, job_id)
    if job is None:
        raise ValueError(f"Job not found: id={job_id}")
    if job.status != JobStatus.RUNNING:
        raise ValueError(f"Cannot pause job in status {job.status.value}")

    # SIGTERM the subprocess if PID is set and alive
    if job.pid is not None:
        try:
            os.kill(job.pid, 0)
            os.kill(job.pid, signal.SIGTERM)
            # Wait briefly for the process to exit
            for _ in range(6):
                time.sleep(0.5)
                try:
                    os.kill(job.pid, 0)
                except OSError:
                    break
        except OSError:
            pass  # PID already dead — just flip the status

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE job
            SET status = 'PAUSED', finished_at = NOW(), updated_at = NOW()
            WHERE id = %s AND status = 'RUNNING'
            """,
            (job_id,),
        )
    conn.commit()

    job.status = JobStatus.PAUSED
    return job


def resume_job(conn, job_id: int) -> Job:
    """Transition a PAUSED job back to TODO for re-pickup by the consumer.

    Clears the PID but preserves session_id and attempt so the consumer's
    existing auto-resume path fires on the next claim.

    Returns the updated Job.
    Raises ValueError if job is not found, not PAUSED, or missing session_id.
    """
    job = fetch_job(conn, job_id)
    if job is None:
        raise ValueError(f"Job not found: id={job_id}")
    if job.status != JobStatus.PAUSED:
        raise ValueError(f"Cannot resume job in status {job.status.value}")
    if job.session_id is None:
        raise ValueError(
            f"Cannot resume job {job_id}: no session_id. "
            "The agent session was not captured before pause."
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE job
            SET status = 'TODO', pid = NULL, scheduled_after = NOW(), updated_at = NOW()
            WHERE id = %s AND status = 'PAUSED'
            """,
            (job_id,),
        )
    conn.commit()

    job.status = JobStatus.TODO
    job.pid = None
    return job
