-- Per-attempt count of ``mcp__toolbox__*`` tool calls observed in the agent's
-- session transcript, populated by ``app_monitor.McpHealthTelemetryObserver``.
-- NULL means the observer could not determine the count (no transcript, no
-- reader for the provider, or parser drift). 0 means the observer read the
-- transcript and found zero toolbox calls.
ALTER TABLE job
    ADD COLUMN toolbox_mcp_calls INT DEFAULT NULL AFTER session_id;
