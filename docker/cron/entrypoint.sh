#!/bin/bash
set -e

# SSH keys + agent credentials are materialized per-agent_view by `workspace:build`
# into builds/<id>/.ssh and builds/<id>/.claude/ (or .codex/). The consumer sets
# HOME=<build_dir> when spawning the agent subprocess, so we no longer prepare
# SSH or config symlinks at container startup.

# Set timezone for cron daemon (reads /etc/localtime, not TZ)
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# Ensure log directory exists and is writable by agent
mkdir -p /app/logs
chown agent /app/logs

# Persist Docker env vars for agent user (su - wipes the environment, cron has its own env)
ENV_FILE=/opt/cron-agent/env
env | grep -E '^(MYSQL_|TZ=|DISABLE_LLM=|PROVIDER=|CONFIG__|AGENTO_)' > "$ENV_FILE"
chmod 644 "$ENV_FILE"

# Minimal crontab header — setup:upgrade populates the AGENTO:BEGIN/END block,
# Jira sync populates the JIRA-SYNC:BEGIN/END block.  Run 'bin/agento setup:upgrade'
# before starting containers to install cron jobs and apply migrations.
ENVLOAD="set -a; source $ENV_FILE; set +a"
cat <<CRONTAB | crontab -u agent -
SHELL=/bin/bash
PATH=${PATH}
HOME=/home/agent

CRONTAB

echo "Cron container started."

# Apply pending migrations and install crontab from module declarations
SETUP_DONE=/tmp/.setup-done
rm -f "$SETUP_DONE"
echo "Running setup:upgrade..."
su - agent -c "set -a; source $ENV_FILE; set +a; /opt/cron-agent/run.sh setup:upgrade --skip-onboarding" || {
    echo "setup:upgrade failed, exiting."
    exit 1
}
touch "$SETUP_DONE"

echo "Crontab after setup:upgrade:"
crontab -u agent -l

# Start consumer as background process (runs as agent user)
echo "Starting consumer process..."
su - agent -c "set -a; source $ENV_FILE; set +a; cd /workspace && /opt/cron-agent/run.sh consumer" &
CONSUMER_PID=$!

# Propagate signals to consumer
trap "kill $CONSUMER_PID 2>/dev/null; wait $CONSUMER_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# Start cron daemon in background
cron -f &
CRON_PID=$!

# Wait for either process to exit (fail-fast)
wait -n $CONSUMER_PID $CRON_PID
