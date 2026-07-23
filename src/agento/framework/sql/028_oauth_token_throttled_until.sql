-- 028: add oauth_token.throttled_until — a temporary usage-limit cooldown.
-- When a provider account hits its session/usage/rate limit, the consumer sets this to the
-- reported reset time (naive UTC) instead of poisoning the token (status='error'). select_token
-- and count_tokens_for_provider skip a token whose throttled_until is in the future and
-- auto-include it once it passes, so the job fails over to a healthy token and the throttled one
-- self-recovers. This is DISTINCT from expires_at (credential expiry: future = still valid).
-- Additive nullable column; safe to re-run only via the schema_migration guard (no IF NOT EXISTS
-- in older MySQL) — the migrator applies each numbered file at most once.
ALTER TABLE oauth_token ADD COLUMN throttled_until DATETIME NULL DEFAULT NULL AFTER expires_at;
