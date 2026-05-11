# Coach Agent

An AI-powered fitness coaching system. Ask natural-language questions about training, nutrition, and programming — the system retrieves answers grounded in a curated fitness knowledge base and returns cited sources.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | ≥ 3.12 | [python.org](https://python.org) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | ≥ 20 | [nodejs.org](https://nodejs.org) |
| pnpm | ≥ 9 | `npm install -g pnpm` |
| Qdrant | ≥ 1.10 | `docker run -p 6333:6333 qdrant/qdrant` |
| PostgreSQL | ≥ 15 | local or Docker |
| Redis | ≥ 7 | local or Docker |

---

## Quick start

### 1. Clone and configure

```bash
git clone <repo-url>
cd coach-agent
```

Copy the environment template and fill in your API keys:

```bash
cp backend/.env.example backend/.env
# edit backend/.env — at minimum set DATABASE_URL, JWT_SECRET,
# ANTHROPIC_API_KEY (for LLM), and OPENAI_API_KEY (for embeddings)
```

### 2. Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# API available at http://localhost:8000
# Swagger UI at http://localhost:8000/docs  (development only)
```

### 3. Ingest the knowledge base

The knowledge base must be ingested into Qdrant before the RAG endpoint can answer questions.
Requires a running Qdrant instance and valid embedding API key (`OPENAI_API_KEY`).

```bash
cd backend
uv run python -m app.rag.ingestion
```

To reingest after document changes:

```bash
uv run python -m app.rag.ingestion --force-recreate
uv run python -m app.rag.ingestion --file ../knowledge-base/08-progressive-overload.md
```

### 4. Frontend

```bash
cd frontend
pnpm install
pnpm dev
# Available at http://localhost:3000
```

---

## API

### `POST /api/v1/rag/query`

Ask a fitness question. Returns a cited answer grounded in the knowledge base.

**Request**

```json
{
  "question": "Is PPL or Upper/Lower better for an intermediate lifter building muscle?",
  "max_sources": 5
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | string | 3–1000 characters |
| `max_sources` | integer | 1–5, default 5 |

**Response**

```json
{
  "answer": "Both splits are effective for intermediate lifters... [1][2]",
  "in_scope": true,
  "sources": [
    {
      "doc_title": "Workout Split Guide",
      "section_title": "PPL Structure",
      "source_file": "14-workout-split-ppl.md",
      "score": 0.82,
      "excerpt": "Push Pull Legs divides training into three movement patterns..."
    }
  ],
  "intent": "COMPARISON",
  "model": "claude-sonnet-4-6",
  "usage": { "prompt_tokens": 480, "completion_tokens": 210, "total_tokens": 690 }
}
```

When `in_scope: false` the answer explains why (off-topic, medical risk, etc.) and `sources` is empty.

### `GET /health`

```json
{ "status": "ok", "env": "development", "version": "0.1.0" }
```

---

## How the RAG pipeline works

```
Question
  │
  ├─ Layer 1: rule filter (regex, ~0 ms)
  │   blocks: off-topic domains, prompt injection
  │
  ├─ Layer 2: LLM intent classifier (~150 ms, only when risk signals found)
  │   labels: SAFE / BORDERLINE / MEDICAL_REFUSE / EATING_RISK / OUT_OF_SCOPE
  │
  ├─ Query processor
  │   SIMPLE     → rewrite (expand abbreviations, add synonyms)
  │   COMPLEX    → decompose into 2–3 sub-questions
  │   COMPARISON → decompose into one sub-question per option
  │
  ├─ Parallel hybrid search (dense + BM25 sparse per sub-question, asyncio.gather)
  │   → RRF merge → diversity filter (max 2 chunks per source file)
  │
  ├─ Context assembly
  │   SIMPLE     → flat relevance-sorted list
  │   COMPLEX    → one section per step
  │   COMPARISON → sides + DISPUTED + SHARED PRINCIPLES sections
  │
  ├─ LLM generation (Claude, temperature=0.2)
  │   returns JSON { "answer": "...", "cited_indices": [...] }
  │
  └─ Layer 3: output filter (bounds-check indices, truncate, inject disclaimers)
```

---

## Knowledge base

20 curated fitness documents in `knowledge-base/`, covering:

| # | Topic |
|---|-------|
| 01–07 | Compound and isolation exercise technique (bench, squat, deadlift, OHP, row, pull-up, isolation) |
| 08–10 | Programming principles (progressive overload, periodization, deload) |
| 11–12 | Intensity metrics and recovery (RPE/RIR, muscle recovery) |
| 13 | Nutrition basics |
| 14–16 | Workout splits (PPL, Upper/Lower, Full Body) |
| 17–20 | 1RM calculation, injury prevention, warm-up/cooldown, beginner guide |

These files are **read-only** — the ingestion pipeline reads them but never writes to them.

---

## Project structure

```
coach-agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Route handlers (thin — delegate to services)
│   │   ├── core/            # Config (pydantic-settings), logging setup
│   │   ├── llm/             # Provider abstraction + factory
│   │   ├── rag/             # Full RAG pipeline (ingestion + query)
│   │   ├── vectordb/        # Qdrant async client wrapper
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── repositories/    # All DB queries
│   │   ├── services/        # Business logic
│   │   └── main.py          # FastAPI app, middleware, lifespan
│   └── tests/
│       ├── mock/            # Offline tests — default CI suite (98 cases)
│       ├── live/            # API integration tests (opt-in, requires keys)
│       └── benchmarks/      # Qdrant search latency benchmarks
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router pages and layouts
│       ├── components/      # UI components (ui/ primitives, feature/ scoped)
│       ├── lib/             # API client, hooks, utilities
│       └── types/           # Shared TypeScript interfaces
├── knowledge-base/          # 20 fitness markdown documents (read-only)
├── sample-data/             # Example workout history JSON
└── docs/
    ├── features/feature_1/  # RAG pipeline design specs
    └── system/              # Architecture, LLM providers, testing guide
```

---

## Running tests

```bash
cd backend

# Default: mock tests only (no API keys needed)
uv run pytest

# Specific file or class
uv run pytest tests/mock/test_guardrails.py -v
uv run pytest tests/mock/test_rag.py::TestChunker -v

# Live tests (fill in .env.test first)
cp .env.test.example .env.test
uv run pytest -m live

# Coverage
uv run coverage run -m pytest && uv run coverage report
```

---

## LLM provider configuration

The default LLM (`DEFAULT_LLM_PROVIDER`) handles generation and intent classification.
The default embedder (`DEFAULT_EMBEDDING_PROVIDER`) handles query and chunk embeddings.
These can be set independently in `.env`:

| Provider | Generation | Embeddings | Key variable |
|----------|:----------:|:----------:|-------------|
| Anthropic (Claude) | ✅ | — | `ANTHROPIC_API_KEY` |
| OpenAI | ✅ | ✅ | `OPENAI_API_KEY` |
| Gemini | ✅ | ✅ | `GEMINI_API_KEY` |
| Grok (xAI) | ✅ | — | `GROK_API_KEY` |
| OpenRouter | ✅ | — | `OPENROUTER_API_KEY` |

Default setup (recommended): `DEFAULT_LLM_PROVIDER=anthropic`, `DEFAULT_EMBEDDING_PROVIDER=openai`.

---

## Documentation

- `docs/features/feature_1/README.md` — RAG pipeline feature overview and design decisions
- `docs/system/testing/` — test scenario catalogue by component
- `docs/system/llm-providers.md` — provider architecture and prompt caching
- `docs/system/vector-database.md` — Qdrant collection schema
- `CLAUDE.md` — guidance for AI coding assistants working in this repo
