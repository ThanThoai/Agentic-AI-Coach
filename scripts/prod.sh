#!/usr/bin/env bash
# prod.sh — Manage the production deployment.
#
# Commands:
#   ./scripts/prod.sh up       — build images and start all services
#   ./scripts/prod.sh down     — stop all services
#   ./scripts/prod.sh restart  — restart all services without rebuilding
#   ./scripts/prod.sh logs     — tail all service logs
#   ./scripts/prod.sh status   — show running containers
#   ./scripts/prod.sh ingest   — re-run knowledge base ingestion
#
# Required env var in shell or backend/.env:
#   PUBLIC_URL    — public-facing URL, e.g. https://yourdomain.com
#                   (baked into frontend build as NEXT_PUBLIC_API_URL)

set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[prod]${NC} $*"; }
warn()  { echo -e "${YELLOW}[prod]${NC} $*"; }
error() { echo -e "${RED}[prod]${NC} $*" >&2; }

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
CMD="${1:-up}"

if [ ! -f backend/.env ]; then
    error "backend/.env not found. Run scripts/setup.sh first."
    exit 1
fi

# Export PUBLIC_URL from .env if not set in shell
if [ -z "${PUBLIC_URL:-}" ]; then
    PUBLIC_URL=$(grep -E '^PUBLIC_URL=' backend/.env | cut -d= -f2- | tr -d '"' || true)
    if [ -z "${PUBLIC_URL}" ]; then
        warn "PUBLIC_URL not set — defaulting to http://localhost"
        PUBLIC_URL="http://localhost"
    fi
fi
export PUBLIC_URL

case "$CMD" in

up)
    info "Building and starting production services..."
    info "PUBLIC_URL = ${PUBLIC_URL}"
    $COMPOSE up --build -d
    info "Waiting for services to be healthy..."
    docker compose wait backend 2>/dev/null || true
    echo
    info "Production deployment is up."
    echo "  Application: ${PUBLIC_URL}"
    echo "  Logs:        ./scripts/prod.sh logs"
    echo "  Status:      ./scripts/prod.sh status"
    ;;

down)
    info "Stopping production services..."
    $COMPOSE down
    info "All services stopped."
    ;;

restart)
    info "Restarting services (no rebuild)..."
    $COMPOSE restart
    info "Services restarted."
    ;;

logs)
    SVCNAME="${2:-}"
    if [ -n "$SVCNAME" ]; then
        $COMPOSE logs -f --tail=100 "$SVCNAME"
    else
        $COMPOSE logs -f --tail=100
    fi
    ;;

status)
    $COMPOSE ps
    ;;

ingest)
    info "Running knowledge base ingestion..."
    # Run inside the backend container (migrations already applied)
    docker compose exec backend uv run python -m app.rag.ingestion
    info "Ingestion complete."
    ;;

*)
    echo "Usage: $0 {up|down|restart|logs [service]|status|ingest}"
    exit 1
    ;;
esac
