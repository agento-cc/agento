-- Minimal source-supplied requester metadata (who triggered the job).
-- Pure metadata: never used for idempotency, dedupe, auth, or routing.
-- requester_trust mirrors RequesterTrust enum (claimed/domain/account).
-- One ADD COLUMN per statement: the migration runner skips a statement on
-- error 1060 (duplicate column), so separate statements stay independently
-- idempotent if the schema is partially drifted.
ALTER TABLE job ADD COLUMN requester_key   VARCHAR(255) NULL AFTER idempotency_key;
ALTER TABLE job ADD COLUMN requester_email VARCHAR(320) NULL AFTER requester_key;
ALTER TABLE job ADD COLUMN requester_trust VARCHAR(32) NOT NULL DEFAULT 'claimed' AFTER requester_email;
ALTER TABLE job ADD COLUMN requester_meta  JSON NULL AFTER requester_trust;

CREATE INDEX idx_job_requester_key ON job (requester_key);
CREATE INDEX idx_job_requester_email ON job (requester_email);
