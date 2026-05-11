# Feature 1 — Fitness Knowledge RAG

**Version:** v1.0 | **Status:** Specced | **Last updated:** 2026-05-11

---

## Requirement

> Build a RAG (Retrieval-Augmented Generation) pipeline that answers fitness-related questions
> using a provided knowledge base (~20 markdown documents).
>
> The system must:
> - Ingest documents, chunk them, and store embeddings in a vector database
> - Accept a natural language question via API and return a grounded answer
> - Include source references (which document/chunk was used) in the response
> - Handle out-of-scope questions gracefully — *"What's the weather today?"* must not produce a fitness answer

---

## Component docs

| File | Scope |
|------|-------|
| [chunking-embedding.md](./chunking-embedding.md) | Parsing knowledge-base docs, chunking strategy, embedding model, Qdrant ingestion |
| [retrieval-generation.md](./retrieval-generation.md) | Query-time vector search, prompt construction, LLM call, response schema |
| [guardrails.md](./guardrails.md) | Out-of-scope detection, abuse prevention, error handling |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 OFFLINE — run once (or whenever knowledge base changes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  knowledge-base/*.md  (20 docs)
          │
          ▼  [chunking-embedding.md]
    Parse by H2 section
          │
          ▼
    Chunk (512 tok max, 64 overlap)
          │
          ▼
    Embed  →  text-embedding-3-small
          │
          ▼
    Upsert → Qdrant  `knowledge_base`  collection


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONLINE — per user request
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/rag/query  { "question": "..." }
          │
          ▼  [guardrails.md]
   Input validation + rate limit check
          │
          ▼  [retrieval-generation.md]
   Embed question  →  same model as ingestion
          │
          ▼
   Qdrant search  top-5  (score ≥ 0.35)
          │
          ├── 0 results ──►  [guardrails.md]  out-of-scope response
          │
          ▼
   Build prompt  (system + context chunks + question)
          │
          ▼
   LLM call  →  { answer, cited_indices }
          │
          ▼
   Map indices → Qdrant payloads  →  source list
          │
          ▼
   Return  RAGResponse  JSON
```

---

## Key design decisions summary

| Decision | Choice | Reason |
|----------|--------|--------|
| Chunk boundary | H2 markdown headers | Each section carries a complete concept; arbitrary token cuts break context |
| Embedding model | `text-embedding-3-small` (1536 dims) | Cost-effective, high quality, matches Qdrant collection dimensions |
| Out-of-scope detection | Two-layer: score threshold + LLM prompt instruction | Fast rejection without LLM cost; prompt fallback for ambiguous cases |
| Source attribution | Server-side index mapping, not LLM-generated | Prevents hallucinated citations; LLM returns indices, server resolves metadata |
| LLM default | Anthropic Claude | Prompt caching on system + context saves ~70% tokens on repeated questions |
| Ingestion idempotency | Deterministic chunk UUID from `sha256(file + index)` | Re-running the ingest script upserts rather than duplicates |

---

## File layout

```
backend/app/rag/
├── __init__.py
├── parser.py          # ParsedChunk dataclass, parse_document(), parse_all()
├── chunker.py         # token-aware splitter with tiktoken
├── embedder.py        # batch embed, provider-agnostic wrapper
├── ingestion.py       # orchestrate parse→chunk→embed→upsert; CLI entry point
└── retriever.py       # embed_query(), search(), out_of_scope gate

backend/app/api/v1/
└── rag.py             # POST /api/v1/rag/query route handler

backend/app/schemas/
└── rag.py             # RAGQuery, RAGSource, RAGResponse pydantic models

backend/tests/mock/
└── test_rag.py        # offline tests for all components

backend/tests/live/
└── test_rag_live.py   # end-to-end with real embeddings + LLM
```

---

## Open questions

1. **Score threshold calibration** — 0.35 is an estimate. Validate with 20–30 labelled
   questions (in-scope + out-of-scope) before shipping.
2. **Supplemental documents** — The requirement allows adding curated content.
   Candidates: TDEE/calorie guide, sleep & recovery, beginner program templates.
   Any additions must be logged in `docs/system/knowledge-base-additions.md`.
3. **Re-ingestion on doc changes** — Upsert handles updates to existing chunks.
   Structural changes (doc split/merge) require a full delete-and-reingest per collection.
4. **Embedding model lock-in** — Qdrant collection dimension is tied to the model.
   Changing providers requires recreating the collection and re-embedding all chunks.
