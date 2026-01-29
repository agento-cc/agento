CREATE TABLE IF NOT EXISTS ingress_identity (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    identity_type   VARCHAR(32)  NOT NULL,
    identity_value  VARCHAR(255) NOT NULL,
    agent_view_id   INT UNSIGNED NOT NULL,
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ingress_type_value (identity_type, identity_value),
    KEY idx_ingress_agent_view (agent_view_id),
    CONSTRAINT fk_ingress_agent_view
        FOREIGN KEY (agent_view_id) REFERENCES agent_view(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
