-- Replace the sticky is_primary flag with a per-provider pool: each token has
-- a health state (status/error_msg), an expiry, and a last-used timestamp.
-- Selection becomes LRU over healthy tokens for the requested provider.
ALTER TABLE oauth_token
    ADD COLUMN status      ENUM('ok','error') NOT NULL DEFAULT 'ok' AFTER enabled,
    ADD COLUMN error_msg   TEXT               NULL                  AFTER status,
    ADD COLUMN expires_at  DATETIME           NULL                  AFTER error_msg,
    ADD COLUMN used_at     DATETIME           NULL                  AFTER expires_at;

ALTER TABLE oauth_token DROP COLUMN is_primary;

CREATE INDEX idx_oauth_token_pool_select
    ON oauth_token (agent_type, enabled, status, used_at);
