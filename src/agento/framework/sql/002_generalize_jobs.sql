-- Migration: generalize jobs table (remove Jira-specific column names)
-- Run manually on existing databases; 001 already has the new schema for fresh installs.

ALTER TABLE jobs
  CHANGE COLUMN agent_type type ENUM('cron', 'todo') NOT NULL,
  CHANGE COLUMN issue_key reference_id VARCHAR(255) NULL;
