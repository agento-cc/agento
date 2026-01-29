-- Store the full prompt sent to the agent and the full response
ALTER TABLE jobs ADD COLUMN prompt MEDIUMTEXT NULL AFTER output_tokens;
ALTER TABLE jobs ADD COLUMN output MEDIUMTEXT NULL AFTER prompt;
