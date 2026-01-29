-- Add module column to schema_migration for module-aware migration tracking.
-- Existing rows default to 'framework'. Idempotent via error code 1060 (duplicate column).
ALTER TABLE schema_migration ADD COLUMN module VARCHAR(255) NOT NULL DEFAULT 'framework';
