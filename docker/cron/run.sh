#!/bin/bash
exec /opt/cron-agent/.venv/bin/python -m agento.framework.cli "$@"
