# Coach Agent — AI Fitness Coaching System

## Project Overview

AI-powered fitness coaching system that analyzes workout history and provides personalized training advice.

**Stack:**
- Backend: FastAPI (Python 3.12+) — managed with **uv**
- Frontend: Next.js 14+ (App Router, TypeScript) — managed with **pnpm**
- Database: PostgreSQL + Redis (cache)
- AI: Claude API (Anthropic SDK)

**Core Domains:**
- Workout tracking & history
- Progressive overload analysis
- Personalized coaching recommendations
- Nutrition guidance
- Injury prevention advice

## Rules Files

| File | Scope |
|------|-------|
| `.claude/rules/fastapi.md` | FastAPI backend patterns |
| `.claude/rules/nextjs.md` | Next.js frontend patterns |
| `.claude/rules/api.md` | API design conventions |
| `.claude/rules/database.md` | Database & migration patterns |
| `.claude/rules/logging.md` | Structured logging standards |
| `.claude/rules/security.md` | Security requirements |

## Key Constraints

- All AI calls must use Claude API with prompt caching enabled
- Workout data units must always be normalized to `kg` before storage
- Knowledge base docs (`knowledge-base/`) are read-only — never modify
- All API endpoints require authentication except `/health` and `/auth/*`
- User workout data is PII — log user IDs only, never raw personal data

## Local Dev Tooling

| Tool | Scope | Purpose |
|------|-------|---------|
| `uv` | Backend (Python) | Virtualenv, dependency install, script runner |
| `pnpm` | Frontend (Node) | Package manager, faster installs via content-addressable store |

**Never use** `pip install`, `npm install`, or `yarn` directly — always go through `uv` and `pnpm` to keep lockfiles consistent.

## Development Commands

```bash
# --- Backend (uv) ---

# Install / sync deps from uv.lock
uv sync

# Add a new dependency
uv add fastapi
uv add --dev pytest

# Run dev server (uv runs inside the managed venv)
uv run uvicorn app.main:app --reload --app-dir backend

# DB migrations
uv run alembic upgrade head

# Run tests
uv run pytest backend/tests

# --- Frontend (pnpm) ---

# Install deps from pnpm-lock.yaml
pnpm install

# Dev server
pnpm --filter frontend dev

# Build
pnpm --filter frontend build

# Tests
pnpm --filter frontend test
```
