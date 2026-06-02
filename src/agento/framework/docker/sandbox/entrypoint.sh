#!/bin/bash
set -e

# SSH keys and agent configs come from per-agent_view workspace builds. Credentials
# are selected again per run and written into the artifacts HOME. The consumer and
# `agento run` set HOME=<artifacts_dir>, so there is nothing to prepare here.

exec gosu agent "$@"
