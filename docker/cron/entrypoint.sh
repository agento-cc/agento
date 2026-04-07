#!/bin/bash
set -e

# Copy SSH key from read-only secret mount to writable .ssh dir with correct permissions
if [ -f /run/secrets/id_rsa ]; then
    mkdir -p /home/agent/.ssh
    chown agent /home/agent/.ssh
    chmod 700 /home/agent/.ssh
    cp /run/secrets/id_rsa /home/agent/.ssh/id_rsa
    chown agent /home/agent/.ssh/id_rsa
    chmod 600 /home/agent/.ssh/id_rsa
fi

# Ensure config files/dirs exist in mounted workspace
# .claude.json must be a file (Claude Code 2.x migration may turn it into a directory)
if [ -d /workspace/.claude.json ]; then
    rm -rf /workspace/.claude.json
fi
[ -s /workspace/.claude.json ] || echo '{}' > /workspace/.claude.json
mkdir -p /workspace/.claude 2>/dev/null || true
mkdir -p /workspace/.codex 2>/dev/null || true
chown agent /workspace/.claude.json /workspace/.claude /workspace/.codex

# Symlink config to home directory (remove real dirs/files first — base image creates them)
rm -rf /home/agent/.claude.json && ln -s /workspace/.claude.json /home/agent/.claude.json
rm -rf /home/agent/.claude && ln -s /workspace/.claude /home/agent/.claude
rm -rf /home/agent/.codex  && ln -s /workspace/.codex  /home/agent/.codex

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
echo "Running setup:upgrade..."
su - agent -c "set -a; source $ENV_FILE; set +a; /opt/cron-agent/run.sh setup:upgrade --skip-onboarding" || {
    echo "setup:upgrade failed, exiting."
    exit 1
}

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
