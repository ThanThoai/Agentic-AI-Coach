# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Stack

- **Backend:** FastAPI (Python 3.12+), SQLAlchemy 2 async, Alembic, Qdrant, structlog — managed with `uv`
- **Frontend:** Next.js 14 App Router, TypeScript, TanStack Query, Zustand, Zod — managed with `pnpm`
- **AI:** Claude API (Anthropic SDK), provider-agnostic LLM abstraction supporting Anthropic / OpenAI / Gemini / Grok / OpenRouter
- **Vector DB:** Qdrant with hybrid named vectors (`dense` 1536-dim + `sparse` BM25 fastembed)

---

## Development commands

All backend commands must be run from `backend/`:

```bash
# Sync dependencies
uv sync

# Dev server
uv run uvicorn app.main:app --reload

# Lint + format check
uv run ruff check .
uv run ruff format --check .

# Type check
uv run mypy app/

# Run all mock tests (CI-safe, no API keys needed)
uv run pytest

# Run a single test file or class
uv run pytest tests/mock/test_guardrails.py -v
uv run pytest tests/mock/test_rag.py::TestChunker -v
uv run pytest tests/mock/test_rag.py::TestChunker::test_overlap_in_split_chunks -v

# Run live tests (requires .env.test with real API keys)
uv run pytest -m live

# Run the knowledge-base ingestion pipeline
uv run python -m app.rag.ingestion
uv run python -m app.rag.ingestion --file knowledge-base/08-progressive-overload.md
uv run python -m app.rag.ingestion --force-recreate

# Search latency benchmark
uv run python -m tests.benchmarks.bench_search --n-queries 300 --warmup 30 --include-bm25

# DB migrations
uv run alembic upgrade head
```

Frontend (run from `frontend/`):

```bash
pnpm install
pnpm dev
pnpm build
pnpm lint
pnpm type-check
pnpm test
```

**Never** use `pip install`, `npm install`, or `yarn` — always `uv` and `pnpm`.

---

## Rules files

Detailed patterns and hard rules live in `.claude/rules/`. Read the relevant file before touching that layer:

| File | Scope |
|------|-------|
| `.claude/rules/fastapi.md` | Route handlers, service/repository split, DI wiring |
| `.claude/rules/api.md` | Versioning, error contract, pagination, idempotency |
| `.claude/rules/database.md` | SQLAlchemy 2 async patterns, N+1 prevention, migration rules |
| `.claude/rules/logging.md` | structlog usage, exception-logging boundary, redaction |
| `.claude/rules/security.md` | Auth, input validation, SSRF prevention, LLM-specific risks |
| `.claude/rules/nextjs.md` | Server/client component split, TanStack Query, API client |

---

## Key constraints

- All LLM calls must use `BaseLLMProvider` (never call provider SDKs directly). Default instances from `app/llm/factory.py` are `@lru_cache` singletons — do not re-instantiate per request.
- Prompt caching is enabled by default on Anthropic; pass `system=` as a kwarg (not inside `messages`) so the system prompt lands in the cache-eligible prefix.
- Workout data units must be normalised to **kg** before storage.
- `knowledge-base/` is read-only — never modify those markdown files.
- All API endpoints require authentication except `GET /health` and `POST /auth/*`.
- Log user IDs only — never raw personal data (email, name, measurements).

---

## Backend architecture

### Entry point and wiring

`app/main.py` owns the FastAPI `lifespan`, middleware stack (CORS, TrustedHost), and router mounting. All v1 routes are aggregated in `app/api/v1/router.py`.

### LLM provider abstraction (`app/llm/`)

`BaseLLMProvider` defines a single interface: `complete()`, `stream()`, `embed()`. Provider implementations (Anthropic, OpenAI, Gemini, Grok, OpenRouter) live in sibling files. `factory.py` maps the `LLMProvider` enum to the correct class — `get_default_llm()` and `get_default_embedder()` are the only two entry points used everywhere else.

Grok and OpenRouter both extend the OpenAI-compatible path (`openai.py` base class with a different `base_url`).

### RAG pipeline (`app/rag/`)

The pipeline has two phases:

**Offline ingestion** (`app.rag.ingestion` CLI):
`parser.py` → `metadata.py` → `chunker.py` → `embedder.py` → `sparse.py` → Qdrant upsert.
Chunk IDs are deterministic UUIDs (`sha256(source_file + "::" + chunk_index)`), making re-ingestion idempotent.

**Online query** (`POST /api/v1/rag/query`):

1. **Guardrails Layer 1** (`guardrails.py` — `hard_block_check`) — regex rule filter for off-topic domains and prompt injection. Free.
2. **Guardrails Layer 2** (`guardrails.py` — `classify_intent`) — LLM intent classifier (Haiku, ~150 ms), triggered only when `needs_intent_classification()` returns `True`. Labels: `SAFE`, `BORDERLINE`, `MEDICAL_REFUSE`, `EATING_RISK`, `OUT_OF_SCOPE`.
3. **Query processing** (`query_processor.py`) — heuristic + LLM classification into `SIMPLE` / `COMPLEX` / `COMPARISON`, then rewrite (SIMPLE, ≤80 chars) or decompose (COMPLEX / COMPARISON → 2–3 sub-questions).
4. **Parallel hybrid search** (`retriever.py`) — `asyncio.gather` over sub-questions; each search embeds the sub-question (dense, 1536-dim) + builds BM25 sparse vector locally, then calls Qdrant `Prefetch[dense top-20, sparse top-20]` + `FusionQuery(RRF)`.
5. **RRF merge + diversity filter** (`retriever.py`) — merges per-sub-question results with Reciprocal Rank Fusion (k=60), then caps at `max_per_source=2` chunks per source file.
6. **Context assembly** (`retriever.py` — `assemble_context`) — selects strategy by query type: `_format_aggregate` (SIMPLE, flat score-sorted), `_format_chain` (COMPLEX, one section per step), `_format_compare` (COMPARISON, sides + DISPUTED + SHARED PRINCIPLES). Conflict detection runs a heuristic O(N²) pass; an optional LLM re-check runs only when candidates are found.
7. **Generation** (`app/api/v1/rag.py` — `generate`) — LLM call with `temperature=0.2`, `max_tokens=512`; expects JSON `{"answer": "...", "cited_indices": [...]}`.
8. **Guardrails Layer 3** (`guardrails.py` — `filter_output`) — parses JSON, bounds-checks indices (1-based, `1 ≤ i ≤ num_chunks`), truncates, injects medical disclaimer if needed.

`retrieve()` returns a tuple `(results_per_query, merged)` — the raw per-sub-question lists are required by `_build_assembled_chunks()` to tag each `AssembledChunk.sub_query_indices`.

### Configuration (`app/core/config.py`)

`Settings` is a `pydantic-settings` class loaded from `.env`. `database_url` and `jwt_secret` are required at startup; everything else has defaults. Access keys via `settings.get_api_key(provider)` — it raises clearly when a key is not set.

### Test tiers

- **Mock** (`tests/mock/`) — default, CI-safe. `respx` intercepts all HTTP; Qdrant uses `:memory:` mode. Runs with plain `uv run pytest`. Conftest loads `.env.test` or falls back to `.env`.
- **Live** (`tests/live/`) — calls real APIs. Requires `.env.test` with keys. Opt-in with `uv run pytest -m live`.
- `MockLLMProvider` (in `tests/mock/conftest.py`) is the standard stub for unit tests. `ControlledMockLLMProvider` (in `test_guardrails.py`) allows per-test response injection for classifier tests.

---

## Frontend architecture

The frontend is a standard Next.js 14 App Router project. Server Components are the default; `"use client"` is added only for event handlers, hooks, and browser APIs. Data fetching uses TanStack Query; client-only UI state uses Zustand. All API calls go through a typed central client in `lib/api/client.ts` — never call `fetch` directly in components. Forms use React Hook Form + Zod with schema files co-located as `*.schema.ts`.
