#!/usr/bin/env bash
# setup.sh — First-time environment setup.
#
# Run once after cloning the repo to:
#   1. Copy .env.example → backend/.env  (then fill in your API keys)
#   2. Start infrastructure (postgres + qdrant)
#   3. Apply database migrations
#   4. Seed demo users and workout data
#   5. Ingest the fitness knowledge base into Qdrant
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh

set -euo pipefail
cd "$(dirname "$0")/.."

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${GREEN}[setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[setup]${NC} $*"; }
error()   { echo -e "${RED}[setup]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── 1. Environment file ───────────────────────────────────────────────────────
section "Environment"
if [ -f backend/.env ]; then
    warn "backend/.env already exists — skipping copy."
else
    cp backend/.env.example backend/.env
    info "Created backend/.env from .env.example"
    warn "Open backend/.env and set your API keys before continuing."
    warn "Required: ANTHROPIC_API_KEY (or OPENAI/OPENROUTER), JWT_SECRET"
    echo
    read -rp "Press Enter once you have filled in backend/.env, or Ctrl-C to abort: "
fi

# ── 2. Infrastructure ─────────────────────────────────────────────────────────
section "Starting infrastructure (postgres + qdrant)"
docker compose up -d postgres qdrant
info "Waiting for postgres..."
docker compose exec postgres sh -c 'until pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"; do sleep 1; done'
info "Waiting for qdrant..."
until curl -sf http://localhost:6333/healthz > /dev/null 2>&1; do sleep 2; done
info "Infrastructure ready."

# ── 3. Database migrations ────────────────────────────────────────────────────
section "Applying database migrations"
cd backend
uv run alembic upgrade head
cd ..
info "Migrations applied."

# ── 4. Seed demo data ─────────────────────────────────────────────────────────
section "Seeding demo users and workout data"
cd backend
uv run python -m scripts.seed_demo
cd ..
info "Demo data seeded."

# ── 5. Knowledge base ingestion ───────────────────────────────────────────────
section "Ingesting knowledge base into Qdrant"
cd backend
uv run python -m app.rag.ingestion
cd ..
info "Knowledge base ingested."

echo
echo -e "${BOLD}${GREEN}Setup complete!${NC}"
echo "Next steps:"
echo "  Development:  ./scripts/dev.sh"
echo "  Production:   ./scripts/prod.sh"
