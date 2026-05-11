# System Architecture

**Version:** 0.1.0 | **Last updated:** 2026-05-11

## Overview

Coach Agent is a multi-tier AI coaching system. Users interact with a Next.js frontend; the FastAPI backend handles business logic, retrieves context from Qdrant, and dispatches to one of several LLM providers.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / Client                          │
│                       Next.js 14 (App Router)                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / SSE
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       FastAPI Backend                            │
│                                                                  │
│  ┌─────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐  │
│  │  API v1  │  │ Services  │  │   Agents  │  │  LLM Factory  │  │
│  │ (routes) │→ │(business) │→ │(coaching) │→ │ Anthropic     │  │
│  └─────────┘  └───────────┘  └───────────┘  │ OpenAI        │  │
│                                              │ Gemini        │  │
│  ┌──────────────────────┐                   │ Grok          │  │
│  │   Repositories       │                   │ OpenRouter    │  │
│  │ (SQLAlchemy async)   │                   └───────────────┘  │
│  └──────────┬───────────┘                                       │
└─────────────┼───────────────────────────────────────────────────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌────────┐ ┌──────┐ ┌────────┐
│Postgres│ │Redis │ │Qdrant  │
│(state) │ │(cache│ │(vector │
│        │ │ jobs)│ │ search)│
└────────┘ └──────┘ └────────┘
```

## Component Responsibilities

### Frontend (`frontend/`)
- Server-side rendered pages via Next.js App Router
- TanStack Query for client-side data synchronisation
- SSE consumer for streaming coaching responses

### Backend (`backend/`)
- `app/api/v1/` — HTTP route handlers (thin, delegate to services)
- `app/services/` — Business logic, orchestration
- `app/agents/` — Coaching agent: context assembly, LLM calls, response formatting
- `app/llm/` — Provider abstraction (see `llm-providers.md`)
- `app/vectordb/` — Qdrant wrapper for knowledge retrieval
- `app/repositories/` — All DB queries via async SQLAlchemy
- `app/models/` — SQLAlchemy ORM models
- `app/schemas/` — Pydantic request/response schemas

### Vector Database (Qdrant)
Two collections:
- `knowledge_base` — 20 fitness knowledge docs, embedded at ingest time
- `workout_embeddings` — User workout notes, embedded for similarity search

### PostgreSQL
Source of truth for user accounts, workout history, and session state.

### Redis
- JWT session cache (30 min TTL)
- Coaching analysis job queue results
- Rate limit sliding-window counters

## Request Flow: Coaching Analysis

```
POST /api/v1/coaching/analyze
        │
        ▼ 1. Authenticate (JWT middleware)
        ▼ 2. Fetch last 90 days of workout sets (PostgreSQL)
        ▼ 3. Embed user query → search knowledge_base (Qdrant)
        ▼ 4. Build prompt: system + knowledge context + workout history + query
        ▼ 5. Stream response from LLM provider (SSE)
        ▼ 6. Store result in Redis (job_id TTL 1h)
```

## Data Flow: Knowledge Ingestion

```
knowledge-base/*.md
        │
        ▼ parse + chunk (512 tokens, 50 overlap)
        ▼ embed via DEFAULT_EMBEDDING_PROVIDER
        ▼ upsert to Qdrant knowledge_base collection
```
