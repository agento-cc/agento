-- Add explicit token type discriminator and priority for pool selection.
-- type defaults to 'oauth' so all existing rows retain today's semantics.
-- priority defaults to 0 so existing LRU ordering is unchanged for tied rows.
-- Refreshed composite index covers WHERE + ORDER BY for select_token().

ALTER TABLE oauth_token
    ADD COLUMN type     VARCHAR(32) NOT NULL DEFAULT 'oauth' AFTER agent_type,
    ADD COLUMN priority INT         NOT NULL DEFAULT 0       AFTER status;

DROP INDEX idx_oauth_token_pool_select ON oauth_token;
CREATE INDEX idx_oauth_token_pool_select
    ON oauth_token (agent_type, enabled, status, priority, used_at);
