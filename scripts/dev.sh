#!/usr/bin/env bash
# dev.sh — Start the development environment.
#
# Modes:
#   ./scripts/dev.sh           — infra only (postgres + qdrant in Docker,
#                                 backend/frontend run locally for best DX)
#   ./scripts/dev.sh docker    — everything in Docker with hot reload
#   ./scripts/dev.sh stop      — stop all dev containers
#
# Prerequisites: backend/.env must exist (run scripts/setup.sh first).

set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info() { echo -e "${GREEN}[dev]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev]${NC} $*"; }

MODE="${1:-local}"

if [ ! -f backend/.env ]; then
    echo "backend/.env not found. Run scripts/setup.sh first."
    exit 1
fi

case "$MODE" in

# ── Infrastructure only + local processes ────────────────────────────────────
local)
    info "Starting infrastructure (postgres + qdrant)..."
    docker compose up -d postgres qdrant

    info "Waiting for postgres..."
    docker compose exec postgres sh -c 'until pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"; do sleep 1; done'

    echo
    echo -e "${BOLD}Infrastructure is up.${NC}"
    echo "Start the backend in another terminal:"
    echo "  cd backend && uv run uvicorn app.main:app --reload --port 8000"
    echo
    echo "Start the frontend in another terminal:"
    echo "  cd frontend && pnpm dev"
    echo
    echo "API:      http://localhost:8000"
    echo "Frontend: http://localhost:3000"
    echo "Qdrant:   http://localhost:6333"
    echo
    echo "Stop infra: ./scripts/dev.sh stop"
    ;;

# ── Full Docker dev (hot reload) ─────────────────────────────────────────────
docker)
    info "Starting full Docker dev environment (hot reload)..."
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.dev.yml \
        up --build
    ;;

# ── Stop ─────────────────────────────────────────────────────────────────────
stop)
    info "Stopping dev containers..."
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.dev.yml \
        down
    info "Dev environment stopped."
    ;;

*)
    echo "Usage: $0 [local|docker|stop]"
    exit 1
    ;;
esac
