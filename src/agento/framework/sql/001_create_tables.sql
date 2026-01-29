CREATE TABLE IF NOT EXISTS schedules (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    issue_key  VARCHAR(20)  NOT NULL,
    summary    VARCHAR(500) NOT NULL DEFAULT '',
    agent_type ENUM('cron', 'todo') NOT NULL,
    cron_expr  VARCHAR(100) NOT NULL DEFAULT '',
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_schedules_issue (issue_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS jobs (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    schedule_id     BIGINT UNSIGNED NULL,
    type            ENUM('cron', 'todo', 'followup') NOT NULL,
    source          VARCHAR(50) NOT NULL DEFAULT 'jira',
    reference_id    VARCHAR(255) NULL,
    context         TEXT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    status          ENUM('TODO', 'RUNNING', 'SUCCESS', 'FAILED', 'DEAD') NOT NULL DEFAULT 'TODO',
    attempt         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    max_attempts    TINYINT UNSIGNED NOT NULL DEFAULT 3,
    scheduled_after TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP NULL,
    finished_at     TIMESTAMP NULL,
    result_summary  TEXT NULL,
    error_message   TEXT NULL,
    error_class     VARCHAR(100) NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_jobs_idempotency (idempotency_key),
    KEY idx_jobs_dequeue (status, scheduled_after),
    KEY idx_jobs_schedule (schedule_id),

    CONSTRAINT fk_jobs_schedule
        FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
