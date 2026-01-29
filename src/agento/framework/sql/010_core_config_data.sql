CREATE TABLE IF NOT EXISTS core_config_data (
    config_id  INT AUTO_INCREMENT PRIMARY KEY,
    scope      VARCHAR(8)   NOT NULL DEFAULT 'default',
    scope_id   INT          NOT NULL DEFAULT 0,
    path       VARCHAR(255) NOT NULL,
    value      TEXT         NULL,
    encrypted  TINYINT(1)   NOT NULL DEFAULT 0,
    updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_scope_path (scope, scope_id, path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
