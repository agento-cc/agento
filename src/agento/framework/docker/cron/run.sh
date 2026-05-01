#!/bin/bash
# agento source comes from host bind-mount; container venv only has its deps.
export PYTHONPATH="/opt/agento-src${PYTHONPATH:+:$PYTHONPATH}"
exec /opt/cron-agent/.venv/bin/python -m agento.framework.cli "$@"
