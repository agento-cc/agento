-- Per-attempt signal of whether the ``toolbox`` MCP server was reported as
-- connected at session start, populated by ``app_monitor.McpHealthTelemetryObserver``.
-- NULL means the provider exposed no init self-report at all ("we don't know").
-- TRUE means the init report listed ``toolbox`` with status="connected".
-- FALSE means the init report existed but ``toolbox`` was absent or not connected.
ALTER TABLE job
    ADD COLUMN toolbox_mcp_connected BOOLEAN DEFAULT NULL AFTER toolbox_mcp_calls;
