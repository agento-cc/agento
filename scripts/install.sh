#!/usr/bin/env bash
# Agento installer — sets up a self-hosted instance via Docker Compose
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[agento]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[agento]${NC} $*"; }
log_error() { echo -e "${RED}[agento]${NC} $*" >&2; }

check_command() {
    if ! command -v "$1" &>/dev/null; then
        log_error "$1 is required but not installed."
        return 1
    fi
}

log_info "Checking prerequisites..."
missing=0
check_command docker || missing=1
docker compose version &>/dev/null 2>&1 || { log_error "docker compose (V2) is required."; missing=1; }
check_command git || missing=1
[ $missing -eq 1 ] && exit 1

INSTALL_DIR="${AGENTO_INSTALL_DIR:-$(pwd)}"

if [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
    log_info "Cloning Agento..."
    git clone https://github.com/saipix/agento.git "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [ ! -f secrets.env ]; then
    cp secrets.env.example secrets.env
    log_warn "Created secrets.env from template."
    log_warn "Please edit secrets.env and fill in your credentials before continuing."
    log_warn "Then re-run this script."
    exit 0
fi

if [ ! -f docker/.env ]; then
    cp docker/.env.example docker/.env
    log_info "Created docker/.env from template."
fi

log_info "Building Docker images..."
cd docker && docker compose build

log_info "Starting containers..."
docker compose up -d

log_info "Waiting for MySQL..."
retries=30
while [ $retries -gt 0 ]; do
    if docker compose exec -T mysql mysqladmin ping -h localhost --silent 2>/dev/null; then
        break
    fi
    retries=$((retries - 1))
    sleep 2
done

cd ..

log_info "Running setup..."
bin/agento setup:upgrade

log_info ""
log_info "Agento installed successfully!"
log_info ""
log_info "Next steps:"
log_info "  1. Register an agent token:  bin/agento token register claude <label>"
log_info "  2. Create your first module:  bin/agento module:add my-app"
log_info "  3. Read the docs:             docs/getting-started.md"
