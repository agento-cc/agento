"""Config keys + domain constants for app_monitor.

Constants are field-relative — they index the dict returned by
``get_module_config("app_monitor")``. See ``system.json`` for the schema and
``config.json`` for the defaults.
"""
from __future__ import annotations

# --- config keys (field-relative, no module prefix) ---

CFG_SEND_ALERT_ON_MCP_ISSUES = "send_alert_on_mcp_issues"

CFG_ALERT_EMAIL_TO       = "alerts/email_to"
CFG_ALERT_SMTP_HOST      = "alerts/smtp_host"
CFG_ALERT_SMTP_PORT      = "alerts/smtp_port"
CFG_ALERT_SMTP_USER      = "alerts/smtp_user"
CFG_ALERT_SMTP_PASSWORD  = "alerts/smtp_password"
CFG_ALERT_SMTP_FROM      = "alerts/smtp_from"
CFG_ALERT_SMTP_TLS       = "alerts/smtp_tls"

# --- telemetry domain constants ---

MCP_TOOLBOX_TOOL_PREFIX = "mcp__toolbox__"

# Minimum number of JSON-parseable lines in a transcript before we treat
# ``recognized_records == 0`` as parser drift (rather than "agent did almost
# nothing"). Production transcripts run dozens of lines; this filter keeps
# trivial 1-or-2-line stubs out of the drift alert.
PARSE_DRIFT_MIN_LINES = 5
