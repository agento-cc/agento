-- Migration: add 'followup' job type and context column for agent self-scheduling
-- Run manually on existing databases; 001 already has the new schema for fresh installs.

ALTER TABLE jobs
  MODIFY COLUMN type ENUM('cron', 'todo', 'followup') NOT NULL;

ALTER TABLE jobs
  ADD COLUMN context TEXT NULL AFTER reference_id;
