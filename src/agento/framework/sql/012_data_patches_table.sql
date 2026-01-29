-- Data patch tracking table (Magento's patch_list equivalent).
-- Separate from schema_migrations: patches are named classes (unordered, idempotent),
-- migrations are numbered SQL files (sequential, position-dependent).
CREATE TABLE IF NOT EXISTS data_patches (
    name        VARCHAR(255) NOT NULL,
    module      VARCHAR(255) NOT NULL,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (module, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
