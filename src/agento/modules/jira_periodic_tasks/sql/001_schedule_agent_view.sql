-- Add agent_view_id to schedule so per-view sync can scope schedules to
-- the owning agent_view. Without this, multi-user installs cannot run
-- separate recurring-task schedules per user (e.g. mieszko vs zyga).

ALTER TABLE schedule
    ADD COLUMN agent_view_id INT UNSIGNED NULL AFTER issue_key,
    ADD KEY idx_schedule_agent_view (agent_view_id),
    ADD CONSTRAINT fk_schedule_agent_view
        FOREIGN KEY (agent_view_id) REFERENCES agent_view(id) ON DELETE SET NULL;

ALTER TABLE schedule
    ADD UNIQUE KEY uq_schedule_agent_view_issue (agent_view_id, issue_key);

ALTER TABLE schedule DROP INDEX uq_schedule_issue;
