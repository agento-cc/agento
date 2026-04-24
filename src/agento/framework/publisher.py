from __future__ import annotations

import logging

from .db import get_connection
from .event_manager import get_event_manager
from .events import JobPublishedEvent
from .job_models import AgentType


def publish(
    config: object,
    agent_type: AgentType,
    source: str,
    idempotency_key: str,
    reference_id: str | None = None,
    max_attempts: int = 3,
    logger: logging.Logger | None = None,
    agent_view_id: int | None = None,
    priority: int = 50,
    skip_if_active: bool = False,
) -> bool:
    """Insert a job into the queue. Returns True if inserted, False if duplicate.

    When ``skip_if_active`` is True and ``reference_id`` is set, the publish is
    skipped if a non-terminal job already exists for the same
    (type, source, agent_view_id, reference_id). Use this when the idempotency
    key rotates on every remote update (e.g. Jira `updated` timestamp), so a
    source-side search-index lag can't produce a duplicate enqueue while the
    original job is still TODO/RUNNING/PAUSED.
    """
    conn = get_connection(config)
    try:
        with conn.cursor() as cur:
            if skip_if_active and reference_id is not None:
                cur.execute(
                    """
                    SELECT 1 FROM job
                    WHERE type = %s AND source = %s
                      AND agent_view_id <=> %s AND reference_id = %s
                      AND status IN ('TODO','RUNNING','PAUSED')
                    LIMIT 1
                    """,
                    (agent_type.value, source, agent_view_id, reference_id),
                )
                if cur.fetchone() is not None:
                    if logger:
                        logger.debug(
                            f"Active job exists, skipping: "
                            f"type={agent_type.value} source={source} "
                            f"ref={reference_id} agent_view_id={agent_view_id}"
                        )
                    return False

            cur.execute(
                """
                INSERT IGNORE INTO job
                    (type, source, agent_view_id, priority, reference_id,
                     idempotency_key, status, attempt, max_attempts)
                VALUES
                    (%s, %s, %s, %s, %s, %s, 'TODO', 0, %s)
                """,
                (agent_type.value, source, agent_view_id, priority,
                 reference_id, idempotency_key, max_attempts),
            )
            conn.commit()
            inserted = cur.rowcount > 0

        if logger:
            if inserted:
                logger.info(
                    f"Published job: type={agent_type.value} source={source} "
                    f"ref={reference_id} key={idempotency_key} "
                    f"agent_view_id={agent_view_id} priority={priority}"
                )
            else:
                logger.debug(f"Duplicate skipped: key={idempotency_key}")

        if inserted:
            get_event_manager().dispatch(
                "job_publish_after",
                JobPublishedEvent(
                    type=agent_type.value,
                    source=source,
                    reference_id=reference_id,
                    idempotency_key=idempotency_key,
                    agent_view_id=agent_view_id,
                    priority=priority,
                ),
            )

        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
