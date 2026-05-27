-- Remove dead oauth_token.model column. The token's model never influenced
-- execution (model resolves from agent_view/model). Safe on fresh installs:
-- the column is absent from init/000_init.sql, so DROP raises 1091 and is skipped.
ALTER TABLE oauth_token DROP COLUMN model;
