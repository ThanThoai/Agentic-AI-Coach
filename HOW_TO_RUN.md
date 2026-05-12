# How to Run — Production Build

Step-by-step guide to build and run the full stack (backend + frontend + nginx) in production mode using Docker Compose.

## Prerequisites

- Docker Engine 24+
- Docker Compose v2 (`docker compose` not `docker-compose`)
- API keys: **OpenRouter** (LLM calls) + **OpenAI** (embeddings)

---

## 1. Configure environment

### Root `.env` (Docker Compose variables)

Create `.env` at the project root if it doesn't exist:

```bash
cp .env.example .env   # if .env.example exists, otherwise create manually
```

Edit `.env`:

| Variable | Value |
|----------|-------|
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | `postgres` |
| `POSTGRES_DB` | `coach_agent` |
| `JWT_SECRET` | generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `PUBLIC_URL` | `http://localhost` (local) or `https://yourdomain.com` (real) |

### Backend `.env` (API keys and app config)

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` — the required fields:

| Variable | Value |
|----------|-------|
| `DEFAULT_LLM_PROVIDER` | `openrouter` |
| `DEFAULT_EMBEDDING_PROVIDER` | `openai` |
| `OPENROUTER_API_KEY` | your OpenRouter key (from openrouter.ai) |
| `OPENAI_API_KEY` | your OpenAI key (used for embeddings only) |

> The following values are **automatically overridden** by Docker Compose at runtime and do not need to be changed in `backend/.env`:
> - `DATABASE_URL` → points to the `postgres` container
> - `QDRANT_URL` → points to the `qdrant` container
> - `APP_ENV` → set to `production` by `docker-compose.prod.yml`
> - `KNOWLEDGE_BASE_PATH` → set to `/app/knowledge-base` (volume mount path)
> - `ENABLE_DEMO_TOKEN` → set to `true` for prod UI testing

---

## 2. Build and start

```bash
./scripts/prod.sh up
```

This command:
1. Builds the backend image (Python + gunicorn)
2. Builds the frontend image (Next.js standalone)
3. Starts postgres and qdrant (waits for healthy)
4. Starts backend — runs `alembic upgrade head` then gunicorn (waits for healthy)
5. Starts frontend and nginx

All services are ready when the command returns. The app is available at `http://localhost:8080`.

---

## 3. Ingest knowledge base

Run once after the first `up`, or after resetting volumes:

```bash
./scripts/prod.sh ingest
```

This ingests all 20 markdown files from `knowledge-base/` into Qdrant (86 chunks, hybrid dense + BM25 sparse vectors). Re-running is safe — chunk IDs are deterministic so it only upserts.

---

## 4. Verify

```bash
# All containers healthy
./scripts/prod.sh status

# nginx responding
curl http://localhost:8080/nginx-health

# Frontend serving
curl -o /dev/null -w "%{http_code}\n" http://localhost:8080/

# Backend health (via nginx → /api/ proxy)
# Note: /health is not under /api/, test directly inside container:
docker exec coach_agent-backend-1 \
  python3 -c "import urllib.request,json; r=urllib.request.urlopen('http://localhost:8000/health'); print(json.loads(r.read()))"

# Demo tokens working (role selector + agent mode in UI)
curl http://localhost:8080/api/v1/auth/demo-token/alex
```

---

## 5. Common commands

```bash
./scripts/prod.sh logs              # tail all service logs
./scripts/prod.sh logs backend      # tail backend logs only
./scripts/prod.sh status            # show container status
./scripts/prod.sh restart           # restart without rebuild
./scripts/prod.sh down              # stop all services (keeps volumes)
```

---

## 6. Reset from scratch

Wipe all data (postgres + qdrant) and rebuild:

```bash
./scripts/prod.sh down              # or: docker compose ... down -v to also remove volumes
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
./scripts/prod.sh up
./scripts/prod.sh ingest
```

---

## Ports

| Port | Service |
|------|---------|
| `8080` | nginx (HTTP — routes to frontend and backend) |
| `8443` | nginx (HTTPS — requires SSL certs in `nginx/ssl/`) |
| `5432` | PostgreSQL (host access for dev tools) |
| `6333` | Qdrant REST API (host access for dev tools) |
| `6334` | Qdrant gRPC |

Backend (8000) and frontend (3000) are **not** exposed in prod mode — all traffic goes through nginx.

---

## HTTPS (optional)

Place certs in `nginx/ssl/`:

```
nginx/ssl/fullchain.pem
nginx/ssl/privkey.pem
```

Then uncomment the HTTPS server block in `nginx/nginx.conf` and update `PUBLIC_URL=https://yourdomain.com` in `.env`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Role selector / agent mode missing | `ENABLE_DEMO_TOKEN` not set | Already set to `true` in `docker-compose.prod.yml` |
| RAG returns "no relevant information" | Knowledge base not ingested | Run `./scripts/prod.sh ingest` |
| Backend unhealthy on startup | `alembic upgrade head` failed | Check `./scripts/prod.sh logs backend` |
| Port 3000 already in use | Dev Next.js server running on host | Kill it: `pkill -f "next-server"` |
| `./scripts/prod.sh up` hangs | Old version of script | Pull latest — `docker compose wait` was removed |
