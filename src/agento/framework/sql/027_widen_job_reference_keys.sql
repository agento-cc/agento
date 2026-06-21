-- 027: widen job.idempotency_key + reference_id for long external IDs.
-- Microsoft Graph message IDs (~150-220 chars) plus the "outlook:mail:" prefix (and, for the
-- readable reference_id, a subject slug) can exceed 255. publish() uses INSERT IGNORE, so under
-- the default STRICT_TRANS_TABLES sql_mode an over-255 value was SILENTLY TRUNCATED — distinct
-- emails sharing a 255-char prefix collided and the second was dropped as a phantom duplicate.
-- utf8mb4 VARCHAR(512) = 2048 bytes < 3072-byte InnoDB large-prefix limit, so the single-column
-- UNIQUE key on idempotency_key stays valid. Do NOT widen to 1024 (4096 > 3072 -> error 1071).
-- Bare MODIFY is idempotent (re-running on an already-512 column is a metadata no-op).
ALTER TABLE job MODIFY COLUMN idempotency_key VARCHAR(512) NOT NULL;
ALTER TABLE job MODIFY COLUMN reference_id    VARCHAR(512) NULL;
