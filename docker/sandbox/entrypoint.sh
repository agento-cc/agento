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
touch /workspace/.claude.json 2>/dev/null || true
mkdir -p /workspace/.claude 2>/dev/null || true
mkdir -p /workspace/.codex 2>/dev/null || true

# Symlink config to home directory
ln -sf /workspace/.claude.json /home/agent/.claude.json
ln -sf /workspace/.claude /home/agent/.claude
ln -sf /workspace/.codex /home/agent/.codex

# Ensure SSH known_hosts exists and contains bitbucket.org
if [ -d /home/agent/.ssh ] && [ ! -f /home/agent/.ssh/known_hosts ]; then
    ssh-keyscan -H bitbucket.org > /home/agent/.ssh/known_hosts 2>/dev/null || true
fi

exec gosu agent "$@"
