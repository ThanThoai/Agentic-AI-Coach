# System Architecture

**Last updated:** 2026-05-12

## Overview

Coach Agent is an AI coaching assistant with three query modes, each backed by a different pipeline. Users interact with a Next.js frontend; the FastAPI backend routes each request to the appropriate service, retrieves context from Qdrant and/or PostgreSQL, and calls an LLM provider.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / Client                          │
│                       Next.js 14 (App Router)                    │
│                                                                  │
│   /question mode   /analysis mode   /agent mode                  │
└──────────┬────────────────┬──────────────────┬───────────────────┘
           │                │                  │
           │       HTTPS / SSE (text/event-stream)
           ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                       FastAPI Backend                            │
│                                                                  │
│  POST /api/v1/rag/query          POST /api/v1/workout/analyze    │
│  POST /api/v1/rag/query/stream   POST /api/v1/workout/analyze/stream │
│                                  POST /api/v1/agent/ask          │
│                                  POST /api/v1/agent/ask/stream   │
│                                                                  │
│  ┌────────────────┐  ┌───────────────────┐  ┌────────────────┐  │
│  │  RAG pipeline  │  │ Workout Analysis  │  │  Agent loop    │  │
│  │ (app/rag/)     │  │ (app/services/    │  │ (app/agent/)   │  │
│  │                │  │  workout.py)      │  │                │  │
│  └───────┬────────┘  └────────┬──────────┘  └───────┬────────┘  │
│          │                    │                      │           │
│          └────────────────────┴──────────────────────┘           │
│                               │                                  │
│                    ┌──────────▼──────────┐                       │
│                    │   LLM Factory        │                       │
│                    │  (app/llm/factory)   │                       │
│                    │  Anthropic / OpenAI  │                       │
│                    │  Gemini / Grok /     │                       │
│                    │  OpenRouter          │                       │
│                    └──────────────────────┘                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Repositories  (app/repositories/)   SQLAlchemy async    │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴─────────────┐
              ▼                          ▼
        ┌──────────┐               ┌──────────┐
        │PostgreSQL│               │  Qdrant  │
        │(workout  │               │(knowledge│
        │ history) │               │  base)   │
        └──────────┘               └──────────┘
```

## Query modes

### /question — RAG pipeline

```
POST /api/v1/rag/query[/stream]
        │
        ▼  Guardrail L1   regex rule filter (free)
        ▼  Guardrail L2   LLM intent classifier (Haiku, ~150 ms; only on risk signals)
        ▼  Query processor  classify (SIMPLE/COMPLEX/COMPARISON) → rewrite or decompose
        ▼  Hybrid search    asyncio.gather over sub-questions
                            dense (text-embedding-3-small, 1536 dim) + sparse (BM25 fastembed)
                            Qdrant Prefetch[top-20 dense, top-20 sparse] + RRF fusion
        ▼  Context assembly  RRF merge, diversity filter (max 2 chunks/source)
                             strategy: aggregate / chain / compare
                             conflict detection: heuristic O(N²) + optional LLM re-check
        ▼  Generation       LLM call (temperature=0.2, max_tokens=512)
        ▼  Guardrail L3     parse JSON, bounds-check citation indices, inject disclaimer
        ▼  RAGResponse      { answer, in_scope, sources, intent, model, usage, trace }
```

### /analysis — Workout history analysis

```
POST /api/v1/workout/analyze[/stream]
        │
        ▼  Auth  user_id from JWT
        ▼  Fetch workout history  (PostgreSQL, scoped to user_id)
        ▼  Analytics engine  compute_analytics() → AnalysisSummary
                             volume, trends, balance, neglect, deload detection
        ▼  Question classifier  (Haiku) → TREND / BALANCE / NEGLECT / PLAN / GENERAL + focus
        ▼  build_llm_context()  structured text block (not raw JSON)
        ▼  Generation  LLM call (temperature=0.3, max_tokens=600), streaming
        ▼  WorkoutAnalysisResponse  { answer, data_summary, question_type, focus, model, usage }
```

### /agent — Coach Assist Agent

```
POST /api/v1/agent/ask[/stream]   (coach role only)
        │
        ▼  AgentService.run_stream()
        ▼  ReAct loop (max 4 iterations, LLM timeout 60 s, tool timeout 45 s)
           keepalive: ping SSE client every 5 s during long waits
                │
                ├─ tool_use  →  execute tools in parallel (asyncio.gather)
                │               rag_search(query)          calls RAG pipeline directly
                │               analyze_history(athlete)   resolves name → user_id via roster
                │
                └─ end_turn  →  yield final answer
        ▼  SSE events: status (tool inputs), token, done (tool_calls detail), ping, error
```

## Component map

| Path | Responsibility |
|------|---------------|
| `app/api/v1/` | HTTP route handlers — thin, delegate to services |
| `app/rag/` | RAG pipeline: guardrails, query processor, retriever, ingestion |
| `app/services/workout.py` | Workout analysis orchestration |
| `app/workout/` | Analytics engine, normalizer, exercise catalog |
| `app/agent/` | Agent loop, tool wrappers, roster, tool schemas |
| `app/prompts/` | All LLM prompts (agent, RAG, workout, guardrail) |
| `app/llm/` | Provider abstraction: `BaseLLMProvider`, factory |
| `app/vectordb/` | Qdrant async wrapper |
| `app/repositories/` | All DB queries via async SQLAlchemy |
| `app/models/` | SQLAlchemy ORM models |
| `app/schemas/` | Pydantic request/response schemas |
| `app/core/` | Config, security (JWT), logging, dependencies |

## Data flow: Knowledge ingestion (offline)

```
knowledge-base/*.md
        │
        ▼  parser.py      parse by H1/H2 section
        ▼  metadata.py    attach topic_type, difficulty, tags
        ▼  chunker.py     512 tok max, 64 overlap, merge < 50 tok
        ▼  embedder.py    text-embedding-3-small → dense vector (1536 dim)
        ▼  sparse.py      BM25 fastembed → sparse vector
        ▼  ingestion.py   upsert to Qdrant (deterministic chunk IDs → idempotent)
```

Run with: `uv run python -m app.rag.ingestion`
