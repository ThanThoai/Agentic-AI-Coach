# Coach Agent

An AI-powered fitness coaching system. Ask natural-language questions about training, nutrition, and programming; analyze your workout history; or run a multi-step coach assistant — all backed by a curated knowledge base with cited sources.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Browser / Mobile                                │
│                      Next.js 14  (App Router)                            │
│                                                                          │
│    /question             /analysis              /agent                   │
└───────┬──────────────────────┬─────────────────────┬────────────────────┘
        │                      │                     │
        │         HTTPS / SSE (text/event-stream)    │
        ▼                      ▼                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          FastAPI  (Python 3.12)                           │
│                                                                          │
│  POST /api/v1/rag/query[/stream]                                         │
│  POST /api/v1/workout/analyze[/stream]                                   │
│  POST /api/v1/agent/ask[/stream]                                         │
│                                                                          │
│  ┌─────────────────────┐  ┌───────────────────────┐  ┌────────────────┐ │
│  │     RAG pipeline    │  │   Workout Analysis    │  │  Agent loop    │ │
│  │   (app/rag/)        │  │  (app/services/       │  │  (app/agent/)  │ │
│  │                     │  │   workout.py)         │  │                │ │
│  │ L1 regex filter     │  │ fetch history (pg)    │  │ ReAct loop     │ │
│  │ L2 LLM guardrail    │  │ analytics engine      │  │ max 4 iters    │ │
│  │ query processor     │  │ question classifier   │  │ tools:         │ │
│  │ hybrid search       │  │ LLM generation        │  │  rag_search    │ │
│  │ context assembly    │  │                       │  │  analyze_hist  │ │
│  │ LLM generation      │  │                       │  │                │ │
│  │ L3 output filter    │  │                       │  │                │ │
│  └──────────┬──────────┘  └──────────┬────────────┘  └───────┬────────┘ │
│             │                        │                        │          │
│             └────────────────────────┴────────────────────────┘          │
│                                      │                                   │
│                          ┌───────────▼──────────┐                        │
│                          │     LLM Factory       │                        │
│                          │  BaseLLMProvider      │                        │
│                          │  Anthropic · OpenAI   │                        │
│                          │  Gemini · Grok        │                        │
│                          │  OpenRouter           │                        │
│                          └──────────────────────┘                        │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │              Repositories  (SQLAlchemy 2 async)                   │   │
│  └───────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
                           │                    │
              ┌────────────┴──┐          ┌──────┴──────────┐
              │  PostgreSQL   │          │     Qdrant       │
              │  workout      │          │  knowledge base  │
              │  history,     │          │  dense 1536-dim  │
              │  auth, events │          │  + sparse BM25   │
              └───────────────┘          └─────────────────-┘
```

### Offline knowledge ingestion (run once before first query)

```
knowledge-base/*.md
    │
    ▼ parser.py    — split by H1/H2 section
    ▼ metadata.py  — attach topic_type, difficulty, tags
    ▼ chunker.py   — 512 tok max, 64 overlap, merge < 50 tok
    ▼ embedder.py  — text-embedding-3-small → dense vector (1536 dim)
    ▼ sparse.py    — BM25 fastembed → sparse vector
    ▼ ingestion.py — upsert to Qdrant (deterministic chunk IDs → idempotent)
```

### RAG query pipeline (online)

```
Question
  ├─ L1: regex rule filter   — off-topic domains, prompt injection   (~0 ms, free)
  ├─ L2: LLM intent classify — Haiku, only on risk signals          (~150 ms)
  │        labels: SAFE / BORDERLINE / MEDICAL_REFUSE / EATING_RISK / OUT_OF_SCOPE
  ├─ Query processor — classify SIMPLE / COMPLEX / COMPARISON
  │        SIMPLE     → rewrite (expand abbrevs, add synonyms)
  │        COMPLEX    → decompose to 2–3 sub-questions
  │        COMPARISON → one sub-question per option
  ├─ Parallel hybrid search (asyncio.gather over sub-questions)
  │        dense top-20 + sparse BM25 top-20 → Qdrant RRF fusion
  │        merge across sub-questions: RRF (k=60), max 2 chunks/source file
  ├─ Context assembly — strategy by query type
  │        SIMPLE     → flat relevance-sorted list
  │        COMPLEX    → one section per step
  │        COMPARISON → sides + DISPUTED + SHARED PRINCIPLES
  │        conflict detection: O(N²) heuristic + optional LLM re-check
  ├─ Generation — LLM call (temperature=0.2, max_tokens=350–512)
  └─ L3: output filter — bounds-check citation indices, truncate, inject disclaimers
```

---

## Quick start (Docker Compose)

### 1. Clone and configure

```bash
git clone <repo-url>
cd coach-agent
cp backend/.env.example backend/.env
```

Edit `backend/.env` — the minimum required variables are:

| Variable | Where to get it |
|----------|----------------|
| `POSTGRES_USER` | Any username, e.g. `coach` |
| `POSTGRES_PASSWORD` | Choose a strong password |
| `POSTGRES_DB` | Any database name, e.g. `coach_agent` |
| `JWT_SECRET` | Random 64-character string (`openssl rand -hex 32`) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) — generation + guardrails |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) — embeddings (`text-embedding-3-small`) |

See `backend/.env.example` for the full list of optional settings.

### 2. Start all services (development)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

| Service | URL |
|---------|-----|
| API + Swagger UI | http://localhost:8000/docs |
| Frontend | http://localhost:3000 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| PostgreSQL | localhost:5432 |

> The backend container runs `alembic upgrade head` automatically on startup before serving requests.

### 3. Ingest the knowledge base

Run once after the containers are healthy:

```bash
docker compose exec backend uv run python -m app.rag.ingestion
```

To force-recreate the collection (after document changes):

```bash
docker compose exec backend uv run python -m app.rag.ingestion --force-recreate
```

### 4. (Optional) Seed demo data

```bash
docker compose --profile seed up seed
```

### 5. Production

```bash
# Uses gunicorn + built Next.js + nginx reverse proxy on :8080
PUBLIC_URL=https://yourdomain.com \
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Place TLS certificates at `nginx/ssl/fullchain.pem` and `nginx/ssl/privkey.pem` for HTTPS on port 8443.

---

## Running without Docker

<details>
<summary>Backend (uv)</summary>

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

Knowledge base ingestion:

```bash
uv run python -m app.rag.ingestion
```

</details>

<details>
<summary>Frontend (pnpm)</summary>

```bash
cd frontend
pnpm install
pnpm dev   # http://localhost:3000
```

</details>

---

## API reference

All endpoints (except `GET /health` and `POST /auth/*`) require a Bearer JWT:

```
Authorization: Bearer <token>
```

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Get JWT |
| POST | `/api/v1/auth/refresh` | Refresh JWT |

### RAG — fitness knowledge query

#### `POST /api/v1/rag/query`

Ask a natural-language fitness question. Returns a cited answer grounded in the knowledge base.

**Request**

```json
{
  "question": "Is PPL or Upper/Lower better for an intermediate lifter building muscle?",
  "max_sources": 5
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | string | 3–1,000 characters |
| `max_sources` | integer | 1–5, default 5 |

**Response `200`**

```json
{
  "answer": "Both splits are effective for intermediates... [1][2]",
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
  "usage": { "prompt_tokens": 480, "completion_tokens": 210, "total_tokens": 690 },
  "trace": {
    "guardrail_l1": { "status": "passed" },
    "guardrail_l2": { "status": "skipped" },
    "query_processor": { "query_type": "COMPARISON", "sub_questions": ["..."] },
    "retrieval": { "results_per_query": [8, 6], "total_merged": 10 },
    "context": { "strategy": "compare", "conflict_count": 1, "chunks_used": 5 }
  }
}
```

When `in_scope: false` the `answer` explains why (off-topic, medical risk, etc.) and `sources` is `[]`.

#### `POST /api/v1/rag/query/stream`

Same request body. Returns `text/event-stream` SSE:

```
data: {"type": "token", "content": "Both splits"}
data: {"type": "token", "content": " are effective..."}
data: {"type": "done", "answer": "...", "in_scope": true, "sources": [...], "trace": {...}}
```

On error: `data: {"type": "error", "message": "..."}`

---

### Workout — history logging and analysis

#### `POST /api/v1/workout/log`  `201`

Log one or more workout entries (max 500 per request). Weights are normalised to **kg** on ingestion.

**Request** — array of entries:

```json
[
  {
    "date": "2026-05-12",
    "exercise": "Bench Press",
    "sets": [
      { "reps": 10, "weight": 80, "unit": "kg" },
      { "reps": 8,  "weight": 85, "unit": "kg" }
    ]
  }
]
```

**Response**

```json
{ "logged": 2, "session_ids": ["uuid-1", "uuid-2"] }
```

#### `POST /api/v1/workout/analyze`

Ask a natural-language question about the authenticated user's stored workout history.

**Request**

```json
{
  "question": "Am I overtraining chest compared to back?",
  "days_back": 30
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | string | 3–500 characters |
| `days_back` | integer | 7–365, default 90 |

**Response `200`**

```json
{
  "answer": "Over the last 30 days, chest volume (18 sets) is 2.6× back volume (7 sets)...",
  "data_summary": {
    "sessions_analysed": 12,
    "exercises_found": 8,
    "date_range": ["2026-04-12", "2026-05-12"]
  },
  "question_type": "BALANCE",
  "focus": "chest",
  "model": "claude-sonnet-4-6",
  "usage": { "prompt_tokens": 620, "completion_tokens": 280, "total_tokens": 900 }
}
```

#### `POST /api/v1/workout/analyze/stream`

Same as `/analyze` but streams tokens as SSE (same event format as RAG stream).

#### `GET /api/v1/workout/sessions`

List the authenticated user's workout sessions (cursor-paginated).

```
GET /api/v1/workout/sessions?limit=20&cursor=<opaque>
```

#### `GET /api/v1/workout/sessions/{session_id}`

Fetch a single session with all sets.

#### `PATCH /api/v1/workout/sessions/{session_id}`

Update session notes or date.

---

### Agent — coach assist (coach role only)

#### `POST /api/v1/agent/ask`

Run a multi-step ReAct agent that can search the knowledge base and analyse athlete history.

**Request**

```json
{
  "message": "Compare Alex's bench press progress to the progressive overload guidelines"
}
```

**Response**

```json
{
  "answer": "Alex has added 12.5 kg to their bench in 8 weeks, which is above the 5–10 kg/month guideline [1]...",
  "tool_calls": [
    { "tool": "analyze_history", "input": {"athlete": "Alex"}, "elapsed_ms": 340 },
    { "tool": "rag_search",      "input": {"query": "progressive overload bench press"}, "elapsed_ms": 210 }
  ],
  "iterations": 2,
  "model": "claude-sonnet-4-6"
}
```

#### `POST /api/v1/agent/ask/stream`

Same request body. SSE events:

```
data: {"type": "status", "tool": "analyze_history", "inputs": {...}}
data: {"type": "token",  "content": "Alex has added..."}
data: {"type": "done",   "answer": "...", "tool_calls": [...], "iterations": 2}
data: {"type": "ping"}   ← keepalive every 5 s during long tool calls
```

---

### Health

#### `GET /health`

```json
{ "status": "ok", "env": "development", "version": "0.1.0" }
```

No authentication required.

---

## Project structure

```
coach-agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Thin route handlers — delegate to services
│   │   │   ├── rag.py       # POST /rag/query[/stream]
│   │   │   ├── workout.py   # POST /workout/log, /analyze[/stream], GET /sessions
│   │   │   ├── agent.py     # POST /agent/ask[/stream]
│   │   │   └── auth.py      # POST /auth/register, /login, /refresh
│   │   ├── core/            # Config (pydantic-settings), JWT, logging
│   │   ├── llm/             # BaseLLMProvider + Anthropic/OpenAI/Gemini/Grok/OpenRouter
│   │   ├── rag/             # Guardrails, query processor, retriever, ingestion
│   │   ├── agent/           # ReAct loop, tool wrappers, roster
│   │   ├── services/        # Business logic (workout analysis, agent orchestration)
│   │   ├── workout/         # Analytics engine, unit normalizer, exercise catalog
│   │   ├── prompts/         # All LLM prompts (versioned, kept out of source code)
│   │   ├── vectordb/        # Qdrant async wrapper
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── repositories/    # All DB queries
│   │   └── main.py          # FastAPI app, middleware, lifespan
│   └── tests/
│       ├── mock/            # Offline tests — default CI suite (no API keys needed)
│       ├── live/            # Integration tests (opt-in: uv run pytest -m live)
│       └── benchmarks/      # Qdrant search latency benchmarks
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router pages and layouts
│       ├── components/      # UI components (ui/ primitives, feature/ scoped)
│       ├── lib/             # Typed API client, TanStack Query hooks, Zustand stores
│       └── types/           # Shared TypeScript interfaces
├── knowledge-base/          # 20 curated fitness markdown docs (read-only)
├── nginx/                   # nginx config for production
├── scripts/                 # dev.sh / prod.sh shortcuts, seed script
└── docs/
    ├── features/            # Feature specs and design docs (feature_1 – feature_6)
    └── system/              # Architecture, LLM providers, vector DB, testing guide
```

---

## Running tests

```bash
cd backend

# Default: mock/offline suite — no API keys needed
uv run pytest

# Specific file or class
uv run pytest tests/mock/test_guardrails.py -v
uv run pytest tests/mock/test_rag.py::TestChunker -v

# Live tests (requires .env.test with real API keys)
cp .env.test.example .env.test
uv run pytest -m live

# Coverage
uv run coverage run -m pytest && uv run coverage report

# Search latency benchmark
uv run python -m tests.benchmarks.bench_search --n-queries 300 --warmup 30
```

---

## Design decisions and tradeoffs

### Hybrid retrieval (dense + sparse BM25)

The RAG pipeline fuses dense vector similarity (text-embedding-3-small, 1536 dim) with BM25 sparse retrieval inside Qdrant using Reciprocal Rank Fusion. Dense search handles semantic paraphrases ("how to increase bench"); sparse search handles exact terminology ("RPE", "1RM", specific exercise names). RRF at k=60 balances both signals without requiring per-query weight tuning.

**Tradeoff:** Two embedding passes per sub-question and a Qdrant `Prefetch` query are slower than a single dense search (~2× latency). The latency cost (~30–50 ms) is worth the recall improvement, especially for technical terms that embeddings tend to conflate.

### Multi-step query decomposition

COMPLEX and COMPARISON questions are decomposed into 2–3 sub-questions before retrieval. Each sub-question runs its own hybrid search; results are merged with RRF and diversity-filtered (max 2 chunks per source file) before context assembly.

**Tradeoff:** Decomposition adds one LLM call (~100 ms for Haiku) and parallel retrieval latency. Single-step queries that are misclassified as COMPLEX get a small accuracy boost at a cost of one extra LLM call. The system errs toward decomposing ambiguous queries.

### Three-layer guardrail design

- **L1 (free):** Regex rule filter blocks obvious off-topic domains (finance, legal, coding) and prompt injection patterns. Zero latency, zero cost.
- **L2 (conditional):** LLM intent classifier (Haiku) runs only when L1 finds risk signals — roughly 10–15% of queries. This keeps per-query LLM call count at 1 for safe queries.
- **L3 (post-generation):** Output filter bounds-checks citation indices and injects medical disclaimers for any BORDERLINE responses that passed through.

**Tradeoff:** A regex-only L1 will occasionally miss novel phrasing. The conditional L2 is a deliberate cost optimization — running Haiku on every query would add ~$0.000025 and ~150 ms per query, which is worth avoiding for clearly safe fitness questions.

### Provider-agnostic LLM abstraction

All LLM calls go through `BaseLLMProvider`. Different pipeline stages use independently configurable providers: Haiku for guardrails and query classification, Sonnet for generation. Swapping providers requires only a change in `.env` — no code changes.

**Tradeoff:** The abstraction layer adds a small indirection cost and limits access to provider-specific features (e.g., Anthropic extended thinking, OpenAI o-series reasoning). For the current feature set this is acceptable; provider-specific features can be added to concrete implementations without breaking the interface.

### Prompt caching (Anthropic)

The system prompt (knowledge context) is passed as the `system=` kwarg to keep it in Anthropic's cache-eligible prefix. At typical context lengths of ~1,000 tokens, caching hits reduce generation cost by ~90% on repeated or similar queries.

**Tradeoff:** Cache invalidates when the context changes (e.g., different retrieved chunks). Comparison queries that assemble a unique context every time benefit less.

### Workout data pre-processing

The workout analysis pipeline computes an `AnalysisSummary` (volume trends, muscle group balance, neglected exercises, deload signals) before the LLM call. The LLM receives a structured text block — not raw JSON — capped at ~1,500 tokens.

**Tradeoff:** Pre-processing adds a Python computation step but dramatically reduces prompt length and LLM confusion. Passing 3 months of raw JSON (potentially thousands of rows) to an LLM is expensive and produces imprecise answers.

### Streaming via SSE

Both RAG and workout analysis support streaming via `text/event-stream`. The backend yields `token` events during generation and a final `done` event with full metadata (sources, trace, usage). The Agent endpoint sends `status` events (tool inputs/outputs) and a `ping` keepalive every 5 seconds during long tool calls.

**Tradeoff:** SSE is simpler than WebSockets for one-directional push. The tradeoff is that the client cannot cancel a request mid-stream; a disconnected client keeps the server-side generator alive until it finishes or times out.

---

## RAG improvement opportunities

The evaluation suite (feature 5, 35 test cases, 3-judge LLM jury) reached **70% pass rate on RAG cases** (7/10) — the lowest of the four categories. The three failures share a clear pattern of fixable root causes.

### 1. Token budget is too tight for complex answers (rag-02, rag-08)

`max_tokens=350` is the single most impactful issue. Two out of three remaining RAG failures were truncated mid-sentence: rag-02 (Progressive Overload + Periodization) cut off before the periodization half of the answer; rag-08 (3-way split comparison) stopped mid-sentence inside the Upper/Lower section.

All three judges scored both answers 3/5 for helpfulness — not because the content was wrong, but because it visibly stopped before the question was fully answered.

**Fix:** Apply an adaptive token budget by query type:

```python
MAX_TOKENS_BY_TYPE = {
    "SIMPLE":     350,
    "COMPLEX":    550,
    "COMPARISON": 600,
}
```

This is a one-line change in `app/api/v1/rag.py`'s `generate()` call. The token increase adds roughly $0.0003–0.0004 per complex query at Sonnet pricing — negligible cost for a meaningful answer completeness improvement.

### 2. Grounding threshold is too permissive for structured answers (rag-02)

`enforce_grounding()` regenerates the answer only when `unsupported_fraction > 0.15`. For rag-02, the model injected two unsupported list items ("Improve Range of Motion", "Improve Technique" as progressive overload methods) — roughly 2 sentences in a 10-sentence list. The fraction was below 0.15, so grounding passed them through.

The problem is that list-item hallucinations feel authoritative to readers and are harder to spot than narrative hallucinations. A flat fraction threshold doesn't distinguish "one unsourced transitional sentence" from "two unsourced items in a factual list."

**Fix:** Apply a stricter threshold specifically to list-format answers, or add a sentence-level check that flags any unsupported item in a `•` / numbered list:

```python
if is_list_format(answer) and unsupported_count >= 1:
    regenerate_with_strict_prompt()
elif unsupported_fraction > 0.15:
    regenerate_with_strict_prompt()
```

### 3. Knowledge base coverage gap — BFR training (rag-10)

rag-10 asks about Blood Flow Restriction training. The knowledge base has no BFR entry, so the retriever correctly returns no results and the endpoint replies with the out-of-scope message. All three judges scored helpfulness 1/5 — not because the pipeline behaved incorrectly, but because BFR is clearly a legitimate, in-scope fitness topic.

**Fix:** Add `21-blood-flow-restriction.md` to `knowledge-base/`. The topic fits naturally alongside the existing intensity-metrics and injury-prevention documents (docs 11–12, 18). After ingestion (`uv run python -m app.rag.ingestion --file knowledge-base/21-blood-flow-restriction.md`), rag-10 should pass without any pipeline changes.

### 4. Eval runner diverges from the endpoint (infrastructure)

`tests/eval/runners/rag_runner.py` reimplements the pipeline directly instead of calling `POST /api/v1/rag/query`. Two endpoint features are currently invisible to the evaluation:

| Endpoint behaviour | In eval? | Cases affected |
|-------------------|----------|---------------|
| OOS detection (`_NO_COVERAGE_RE` substitution) | No | rag-10 |
| BORDERLINE grounding skip (`was_borderline=True`) | No | adv-10 |

This means the eval **understates** actual endpoint quality for these two cases: the endpoint would return a clean out-of-scope message for rag-10, and would skip the over-aggressive grounding rewrite for adv-10. Both would likely pass if the runner matched the endpoint.

**Fix:** Refactor `rag_runner.py` to call the endpoint via `httpx.AsyncClient` (or at minimum import and call the same `query_rag()` handler function), so there is a single code path to test.

---

### Summary

| Issue | Cases | Effort | Expected gain |
|-------|-------|--------|--------------|
| Adaptive token budget (COMPLEX/COMPARISON) | rag-02, rag-08 | ~1 line | +20 pp RAG pass rate |
| Stricter list-item grounding threshold | rag-02 | ~10 lines | +10 pp faithfulness score |
| Add BFR knowledge-base entry | rag-10 | ~1 doc | Closes one coverage gap |
| Sync `rag_runner.py` with endpoint | rag-10, adv-10 | Medium refactor | Eval accuracy, not pipeline accuracy |

Addressing items 1 and 2 alone would bring the RAG pass rate from **70% → 90%**, matching the adversarial and workout category scores.

---

## Cost estimate

Default provider configuration: **Claude Haiku 4.5** for guardrails and query classification; **Claude Sonnet 4.6** for generation; **OpenAI text-embedding-3-small** for embeddings.

### Per-query cost breakdown

#### Feature 1 — RAG Query

| Step | Model | Avg tokens | Cost/query |
|------|-------|-----------|-----------|
| Embedding (query) | text-embedding-3-small | ~200 | ~$0.000004 |
| L2 guardrail (10% of queries) | Haiku | 250 in + 50 out | ~$0.000003 avg |
| Query classification | Haiku | 150 in + 30 out | ~$0.000015 |
| Generation | Sonnet | ~1,000 in + 300 out | ~$0.0075 |

**Observed range: $0.0006 – $0.0008 per query** (with prompt caching applied; cached hits reduce Sonnet input cost ~90%)

At **1,000 queries/day**:

| | Low estimate | High estimate |
|-|-------------|--------------|
| Daily | **$0.60** | **$0.80** |
| Monthly (30 days) | **$18** | **$24** |

#### Feature 2 — Workout History Analysis

Each analysis adds a Haiku question-classification call and scales generation input with history length.

| Step | Model | Avg tokens | Cost/query |
|------|-------|-----------|-----------|
| Question classifier | Haiku | 200 in + 30 out | ~$0.00018 |
| Generation (short history ~30 days) | Sonnet | ~500 in + 300 out | ~$0.006 |
| Generation (long history ~3 months) | Sonnet | ~1,500 in + 400 out | ~$0.0105 |

**Observed range: $0.0008 – $0.0018 per query** (with prompt caching; cost scales with history window)

At **1,000 queries/day**:

| | Low estimate | High estimate |
|-|-------------|--------------|
| Daily | **$0.80** | **$1.80** |
| Monthly (30 days) | **$24** | **$54** |

### Combined estimate at 1,000 queries/day (both features)

```
Feature          Daily low   Daily high   Monthly low   Monthly high
────────────────────────────────────────────────────────────────────
RAG Query        $0.60       $0.80        $18           $24
Workout Analysis $0.80       $1.80        $24           $54
────────────────────────────────────────────────────────────────────
Total            $1.40       $2.60        $42           $78
```

> **Note:** Prompt caching is the largest cost lever. A cold-start query (cache miss) can cost 5–10× more than a cache-hit query. The estimates above assume a warm cache typical of sustained production traffic. The LLM pricing above reflects Anthropic public list prices as of mid-2026; verify current rates at [anthropic.com/pricing](https://anthropic.com/pricing).

---

## LLM provider configuration

The generation and embedding providers can be set independently in `.env`:

| Provider | Generation | Embeddings | Key variable |
|----------|:----------:|:----------:|-------------|
| Anthropic (Claude) | ✅ | — | `ANTHROPIC_API_KEY` |
| OpenAI | ✅ | ✅ | `OPENAI_API_KEY` |
| Gemini | ✅ | ✅ | `GEMINI_API_KEY` |
| Grok (xAI) | ✅ | — | `GROK_API_KEY` |
| OpenRouter | ✅ | — | `OPENROUTER_API_KEY` |

Recommended default: `DEFAULT_LLM_PROVIDER=anthropic`, `DEFAULT_EMBEDDING_PROVIDER=openai`.

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

These files are **read-only** — ingest them but never edit them.

---

## Documentation

| Path | Contents |
|------|----------|
| `docs/system/architecture.md` | Detailed pipeline diagrams and component map |
| `docs/system/llm-providers.md` | Provider architecture and prompt caching guide |
| `docs/system/vector-database.md` | Qdrant collection schema and indexing config |
| `docs/features/feature_1/` | RAG pipeline design and evaluation |
| `docs/features/feature_2.md` | Workout analysis spec |
| `docs/features/feature_3.md` | Agent spec |
| `docs/features/feature_6.md` | Usage metering and cost quota system design |
| `CLAUDE.md` | Guidance for AI coding assistants working in this repo |
