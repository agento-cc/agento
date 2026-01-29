-- Add 'blank' job type for e2e tests
ALTER TABLE jobs
  MODIFY COLUMN type ENUM('cron', 'todo', 'followup', 'blank') NOT NULL;
