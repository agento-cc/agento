#!/bin/bash
# Run command in AI sandbox container
# Usage: bin/run-sandbox.sh <command> [args...]
#
# Examples:
#   bin/run-sandbox.sh bin/mssql "SELECT @@VERSION"
#   bin/run-sandbox.sh claude -p "explain this code"
#   bin/run-sandbox.sh codex "refactor this"

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR/docker"

# Export current user's UID/GID for Docker to match permissions
export HOST_UID=$(id -u)
export HOST_GID=$(id -g)

# Check for authentication files (in project directory)
AUTH_MISSING=0

if [ ! -f "$PROJECT_DIR/workspace/.codex/auth.json" ]; then
    echo "WARNING: Codex auth file not found (workspace/.codex/auth.json)"
    echo "  To authenticate Codex:"
    echo "    1. Run 'codex' in your normal terminal (not in Docker)"
    echo "    2. Complete the browser authentication"
    echo "    3. Copy auth file: cp ~/.codex/auth.json $PROJECT_DIR/workspace/.codex/"
    echo ""
    AUTH_MISSING=1
fi

if [ ! -f "$PROJECT_DIR/workspace/.claude/.credentials.json" ]; then
    echo "WARNING: Claude credentials not found (workspace/.claude/.credentials.json)"
    echo "  To authenticate Claude:"
    echo "    1. Run 'claude' in your normal terminal (not in Docker)"
    echo "    2. Complete the browser authentication"
    echo "    3. Copy credentials: cp ~/.claude/.credentials.json $PROJECT_DIR/workspace/.claude/"
    echo ""
    AUTH_MISSING=1
fi

if [ "$AUTH_MISSING" -eq 1 ]; then
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Ensure .claude.json state file exists (needed to skip onboarding screens)
if [ ! -f "$PROJECT_DIR/workspace/.claude.json" ]; then
    echo '{"hasCompletedOnboarding":true,"numStartups":1}' > "$PROJECT_DIR/workspace/.claude.json"
fi

# Build images if not exists or if UID changed
# We tag with UID to detect when rebuild is needed
EXPECTED_TAG="agento-sandbox:uid-${HOST_UID}"
if ! docker image inspect "$EXPECTED_TAG" >/dev/null 2>&1; then
    echo "Building sandbox container for UID ${HOST_UID}..."
    docker compose build sandbox
    docker tag agento-sandbox:latest "$EXPECTED_TAG"
fi

if ! docker image inspect "agento-toolbox:latest" >/dev/null 2>&1; then
    echo "Building toolbox container..."
    docker compose build toolbox
fi

# Start toolbox in background (sandbox depends on it)
docker compose up -d toolbox

# No args = interactive bash
if [ $# -eq 0 ]; then
    docker compose run --rm sandbox bash
    exit $?
fi

# Run command in container
docker compose run --rm sandbox "$@"
