-- Move OAuth credentials from filesystem paths into an encrypted column.
-- Hard break: no backward compatibility — users must re-register tokens.
ALTER TABLE oauth_token
    DROP COLUMN credentials_path,
    ADD COLUMN credentials MEDIUMTEXT NULL AFTER label;
