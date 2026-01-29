-- Agent Manager: token registry and usage tracking.
-- For existing databases, run this file manually:
--   mysql -u cron_agent -p cron_agent < 005_agent_manager.sql

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    agent_type       VARCHAR(20)  NOT NULL,          -- 'claude', 'codex'
    label            VARCHAR(100) NOT NULL,
    credentials_path VARCHAR(500) NOT NULL,
    token_limit      BIGINT UNSIGNED NOT NULL DEFAULT 0,   -- 0 = unlimited
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_oauth_tokens_label (label),
    KEY idx_oauth_tokens_agent_enabled (agent_type, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS usage_log (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    token_id         BIGINT UNSIGNED NOT NULL,
    tokens_used      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    input_tokens     BIGINT UNSIGNED NOT NULL DEFAULT 0,
    output_tokens    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    reference_id     VARCHAR(255) NULL,
    duration_ms      INT UNSIGNED NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_usage_token_time (token_id, created_at),
    CONSTRAINT fk_usage_token FOREIGN KEY (token_id) REFERENCES oauth_tokens(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
