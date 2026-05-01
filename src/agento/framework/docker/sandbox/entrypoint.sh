#!/bin/bash
set -e

# SSH keys + agent credentials now come from per-agent_view workspace builds.
# `workspace:build` materializes them into builds/<id>/.ssh/ and builds/<id>/.claude/
# (or .codex/); the consumer sets HOME=<build_dir> when spawning the agent process,
# so there is nothing to prepare at container startup.

exec gosu agent "$@"
