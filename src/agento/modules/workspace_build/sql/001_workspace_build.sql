CREATE TABLE IF NOT EXISTS workspace_build (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    agent_view_id   INT UNSIGNED NOT NULL,
    build_dir       VARCHAR(500) NOT NULL,
    checksum        VARCHAR(64)  NOT NULL DEFAULT '',
    status          ENUM('building', 'ready', 'failed') NOT NULL DEFAULT 'building',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_build_agent_view (agent_view_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
