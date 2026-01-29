-- Phase 9.5: Job priority for concurrent agent_view execution pool.
-- Priority range 0-100 (higher = earlier execution), default 50.

ALTER TABLE job ADD COLUMN priority TINYINT UNSIGNED NOT NULL DEFAULT 50 AFTER agent_view_id;

CREATE INDEX idx_job_priority_created ON job (priority DESC, created_at ASC);
