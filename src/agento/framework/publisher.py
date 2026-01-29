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
) -> bool:
    """Insert a job into the queue. Returns True if inserted, False if duplicate."""
    conn = get_connection(config)
    try:
        with conn.cursor() as cur:
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
                "job_published",
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
