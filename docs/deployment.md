# Deployment Guide

**Last updated:** 2026-05-12

---

## Overview

Coach Agent runs as four services:

| Service | Technology | Port |
|---------|-----------|------|
| **backend** | FastAPI (Python 3.12) | 8000 (internal) |
| **frontend** | Next.js 14 standalone | 3000 (internal) |
| **postgres** | PostgreSQL 16 | 5432 |
| **qdrant** | Qdrant v1.11 | 6333 |
| **nginx** *(prod only)* | nginx 1.27 | 80 / 443 |

In **development**, the backend and frontend run locally with hot reload; postgres and qdrant run in Docker.  
In **production**, everything runs in Docker behind nginx.

---

## Prerequisites

- Docker ≥ 24 + Docker Compose V2 (`docker compose` not `docker-compose`)
- Python 3.12 + [`uv`](https://docs.astral.sh/uv/) (for running migrations and ingestion locally)
- Node.js 20 + pnpm (only needed if running frontend locally in dev)
- At least one LLM API key: Anthropic, OpenAI, Gemini, Grok, or OpenRouter

---

## First-Time Setup

Run the setup script once after cloning:

```bash
chmod +x scripts/setup.sh scripts/dev.sh scripts/prod.sh
./scripts/setup.sh
```

The script will:
1. Copy `backend/.env.example` → `backend/.env` (you fill in API keys)
2. Start postgres and qdrant
3. Apply Alembic database migrations
4. Seed demo users (Alex, Binh, coach) and workout history
5. Ingest the fitness knowledge base into Qdrant

### Manual setup

If you prefer to run each step yourself:

```bash
# 1. Create .env
cp backend/.env.example backend/.env
# Edit backend/.env — set at minimum: JWT_SECRET and one LLM API key

# 2. Start infrastructure
docker compose up -d postgres qdrant

# 3. Apply migrations (from backend/)
cd backend
uv run alembic upgrade head

# 4. Seed demo data
uv run python -m scripts.seed_demo

# 5. Ingest knowledge base
uv run python -m app.rag.ingestion
cd ..
```

---

## Development

### Option A — Local processes (recommended)

Best developer experience: hot reload with no Docker overhead for the app.

```bash
# Start postgres + qdrant only
./scripts/dev.sh
# or equivalently:
docker compose up -d postgres qdrant

# Backend (separate terminal, from backend/)
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal, from frontend/)
cd frontend
pnpm dev
```

Access points:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Qdrant dashboard: http://localhost:6333/dashboard

### Option B — Full Docker dev (hot reload via volume mounts)

```bash
./scripts/dev.sh docker
# or:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Stop dev environment

```bash
./scripts/dev.sh stop
# or just Ctrl-C if running in the foreground
```

---

## Production

### Architecture

```
Internet
    │
    ▼
nginx :80/:443
    ├── /api/*  ──────────────► backend:8000  (gunicorn + uvicorn workers)
    ├── /_next/static/*  ──────► frontend:3000 (Next.js standalone)
    └── /*  ────────────────────► frontend:3000 (Next.js SSR)
```

nginx disables proxy buffering on `/api/*` so SSE streams (RAG, workout, agent) flow through immediately.

### Environment configuration

Edit `backend/.env` based on `backend/.env.example`. The minimum required variables for production:

```bash
# Generate a secure JWT secret:
python -c "import secrets; print(secrets.token_hex(32))"
```

| Variable | Value |
|----------|-------|
| `APP_ENV` | `production` |
| `JWT_SECRET` | ≥ 32-char random hex (generate above) |
| `PUBLIC_URL` | `https://yourdomain.com` or `http://your-server-ip` |
| `ANTHROPIC_API_KEY` | Your Anthropic key (if using Anthropic) |
| `OPENAI_API_KEY` | Your OpenAI key (required for embeddings) |
| `GUNICORN_WORKERS` | `4` (tune: 2 × CPU_CORES + 1) |

### Start production

```bash
./scripts/prod.sh up
```

This will:
1. Build the backend image (with gunicorn)
2. Build the frontend image (Next.js standalone, baking in `NEXT_PUBLIC_API_URL`)
3. Start all services: postgres, qdrant, backend, frontend, nginx
4. Apply migrations automatically via `docker-entrypoint.sh`

### Manage production

```bash
./scripts/prod.sh status          # show running containers
./scripts/prod.sh logs            # tail all logs
./scripts/prod.sh logs backend    # tail backend only
./scripts/prod.sh restart         # restart without rebuilding
./scripts/prod.sh down            # stop all services
./scripts/prod.sh ingest          # re-run knowledge base ingestion
```

### Update deployment (new code)

```bash
git pull
./scripts/prod.sh up              # rebuilds changed images, applies migrations
```

---

## HTTPS / SSL

Place your certificate files in `nginx/ssl/`:

```
nginx/ssl/
├── fullchain.pem
└── privkey.pem
```

Then uncomment the HTTPS server block in `nginx/nginx.conf` and uncomment the `return 301` redirect in the HTTP block. Restart nginx:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

For Let's Encrypt (Certbot), the standard approach is:
1. Get a certificate on the host: `certbot certonly --standalone -d yourdomain.com`
2. Symlink `/etc/letsencrypt/live/yourdomain.com/` → `nginx/ssl/`
3. Add a cron job: `0 3 * * * certbot renew --quiet && docker compose ... restart nginx`

---

## Knowledge Base Ingestion

The fitness knowledge base in `knowledge-base/` must be ingested into Qdrant before RAG queries work. This is done once during setup and again whenever documents change.

```bash
# Ingest all documents (idempotent — safe to re-run)
cd backend
uv run python -m app.rag.ingestion

# Ingest a single file
uv run python -m app.rag.ingestion --file knowledge-base/08-progressive-overload.md

# Force recreate the Qdrant collection (drops and rebuilds)
uv run python -m app.rag.ingestion --force-recreate
```

In production (running inside Docker):
```bash
./scripts/prod.sh ingest
# or directly:
docker compose exec backend uv run python -m app.rag.ingestion
```

Chunk IDs are deterministic (`sha256(source_file::chunk_index)`), so re-ingestion is idempotent — existing chunks are upserted, not duplicated.

---

## Database Migrations

Migrations run automatically at container start via `docker-entrypoint.sh`. To run manually:

```bash
# Apply all pending migrations
cd backend && uv run alembic upgrade head

# Check current migration state
uv run alembic current

# Create a new migration
uv run alembic revision --autogenerate -m "describe the change"
```

Never edit a merged migration — write a new one instead. See `.claude/rules/database.md` for the full migration policy.

---

## Configuration Reference

All backend configuration is in `backend/.env`. See `backend/.env.example` for the full annotated list.

Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | yes | `development` or `production` |
| `JWT_SECRET` | yes | ≥ 32-char random string for signing tokens |
| `PUBLIC_URL` | prod | Public URL (baked into frontend build) |
| `GUNICORN_WORKERS` | prod | Worker processes (default: 4) |
| `DATABASE_URL` | local dev | Set when running backend outside Docker |
| `QDRANT_URL` | yes | Qdrant endpoint (default: `http://localhost:6333`) |
| `DEFAULT_LLM_PROVIDER` | yes | `anthropic` / `openai` / `gemini` / `grok` / `openrouter` |
| `DEFAULT_EMBEDDING_PROVIDER` | yes | `openai` (recommended) |
| `ANTHROPIC_API_KEY` | if using Anthropic | Claude API key |
| `OPENAI_API_KEY` | if using OpenAI/embeddings | OpenAI API key |

---

## Gunicorn Worker Count

The default is 4 workers. Tune with `GUNICORN_WORKERS` in `.env`.

| Server size | Suggested workers |
|-------------|-------------------|
| 2 vCPU | 5 |
| 4 vCPU | 9 |
| 8 vCPU | 17 |

Formula: `2 × CPU_CORES + 1`

Each worker handles concurrent requests via asyncio — you do **not** need one worker per concurrent request.

---

## Troubleshooting

**Backend won't start — `DATABASE_URL` error**  
Make sure postgres is healthy before backend starts. The `depends_on: condition: service_healthy` in docker-compose handles this, but if postgres takes longer than expected: `docker compose restart backend`.

**Qdrant collection missing — RAG returns empty results**  
Run ingestion: `./scripts/prod.sh ingest`

**SSE streaming stops or hangs through nginx**  
Check that `proxy_buffering off` is set in `nginx/nginx.conf` for `/api/` — this is required for SSE.

**Frontend shows API errors in production**  
`NEXT_PUBLIC_API_URL` is baked into the frontend at build time. If `PUBLIC_URL` was wrong when you ran `./scripts/prod.sh up`, rebuild: `./scripts/prod.sh down && ./scripts/prod.sh up`.

**Permission denied on scripts**  
```bash
chmod +x scripts/setup.sh scripts/dev.sh scripts/prod.sh
```
