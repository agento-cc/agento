-- Preserve fair LRU rotation for rapid same-priority token claims.
ALTER TABLE oauth_token
    MODIFY COLUMN used_at DATETIME(6) NULL;

DROP INDEX idx_oauth_token_pool_select ON oauth_token;
CREATE INDEX idx_oauth_token_pool_select
    ON oauth_token (agent_type, enabled, status, priority, used_at);
