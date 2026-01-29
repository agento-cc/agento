-- Phase 9: Workspace & Agent View hierarchy
-- workspace: organizational unit for grouping agent_views
-- agent_view: runtime identity — one agent_view = one config set + one working directory

CREATE TABLE IF NOT EXISTS workspace (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL,
    label       VARCHAR(255) NOT NULL DEFAULT '',
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_workspace_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_view (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    workspace_id  INT UNSIGNED NOT NULL,
    code          VARCHAR(50)  NOT NULL,
    label         VARCHAR(255) NOT NULL DEFAULT '',
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_view_code (code),
    KEY idx_agent_view_workspace (workspace_id),
    CONSTRAINT fk_agent_view_workspace
        FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Widen core_config_data.scope to fit 'workspace' and 'agent_view' scope names.
-- Existing rows use scope='default', scope_id=0 (global).
-- New scopes: 'workspace' (scope_id = workspace.id), 'agent_view' (scope_id = agent_view.id).
ALTER TABLE core_config_data MODIFY scope VARCHAR(16) NOT NULL DEFAULT 'default';

-- Add agent_view_id to job table for routing
ALTER TABLE job ADD COLUMN agent_view_id INT UNSIGNED NULL AFTER source;
ALTER TABLE job ADD KEY idx_job_agent_view (agent_view_id);
ALTER TABLE job ADD CONSTRAINT fk_job_agent_view
    FOREIGN KEY (agent_view_id) REFERENCES agent_view(id) ON DELETE SET NULL;
