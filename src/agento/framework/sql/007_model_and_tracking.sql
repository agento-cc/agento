-- Model + primary flag on tokens
ALTER TABLE oauth_tokens ADD COLUMN model VARCHAR(50) NULL AFTER credentials_path;
ALTER TABLE oauth_tokens ADD COLUMN is_primary TINYINT(1) NOT NULL DEFAULT 0 AFTER model;

-- Model tracking in usage_log
ALTER TABLE usage_log ADD COLUMN model VARCHAR(50) NULL AFTER output_tokens;

-- Job execution tracking (denormalized — jobs are historical, no FK to tokens)
ALTER TABLE jobs ADD COLUMN agent_type VARCHAR(20) NULL AFTER reference_id;
ALTER TABLE jobs ADD COLUMN model VARCHAR(50) NULL AFTER agent_type;
ALTER TABLE jobs ADD COLUMN input_tokens BIGINT UNSIGNED NULL AFTER model;
ALTER TABLE jobs ADD COLUMN output_tokens BIGINT UNSIGNED NULL AFTER input_tokens;
