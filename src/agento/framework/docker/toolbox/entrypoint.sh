#!/bin/bash
set -e

# Toolbox has no agent secrets — no SSH/credentials to materialize at startup.
# We just drop privileges from root to the agent user so files written into
# the shared workspace/artifacts volume match the cron consumer's UID/GID.
exec gosu agent "$@"
