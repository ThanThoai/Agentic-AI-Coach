# Feature 1 — Fitness Knowledge RAG

**Version:** v1.1 | **Status:** Implemented | **Last updated:** 2026-05-11

---

## Requirement

> Build a RAG (Retrieval-Augmented Generation) pipeline that answers fitness-related questions
> using a provided knowledge base (~20 markdown documents).
>
> The system must:
> - Ingest documents, chunk them, and store hybrid (dense + sparse) embeddings in a vector database
> - Accept a natural language question via API and return a grounded, cited answer
> - Classify and decompose queries before retrieval to optimise multi-part and comparison questions
> - Include source references (document, section, excerpt, score) in the response
> - Guard against off-topic questions, medical risk, prompt injection, and harmful content

---

## Component docs

| File | Scope |
|------|-------|
| [chunking-embedding.md](./chunking-embedding.md) | Parsing knowledge-base docs, chunking strategy, metadata enrichment, hybrid embedding, Qdrant ingestion |
| [retrieval-generation.md](./retrieval-generation.md) | Query classification, rewriting, decomposition, parallel hybrid retrieval, RRF merge, context assembly strategies, conflict detection, generation |
| [guardrails.md](./guardrails.md) | 3-layer guardrail pipeline — rule filter, LLM intent classifier, output filter |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 OFFLINE — run once (or whenever the knowledge base changes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  knowledge-base/*.md  (~20 docs)
          │
          ▼  parser.py
    Parse by H1 / H2 section
          │
          ▼  metadata.py
    Attach topic_type, difficulty, tags
          │
          ▼  chunker.py
    Chunk (512 tok max, 64 overlap, merge < 50 tok)
          │
          ▼  embedder.py
    Embed prefix + body → text-embedding-3-small (1536 dims)
    Build BM25 sparse vector (fastembed, local)
          │
          ▼  ingestion.py
    Upsert → Qdrant  `knowledge_base`  collection
             (deterministic UUID per chunk — idempotent)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONLINE — per user request
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/rag/query  { "question": "...", "max_sources": 5 }
          │
          ▼  guardrails.py  — Layer 1
    Hard-block regex filter
    (off-topic domains, prompt injection, jailbreak)
          │ blocked → 200 out-of-scope response
          ▼
    needs_intent_classification()?
          │ yes
          ▼  guardrails.py  — Layer 2
    LLM intent classifier (Haiku, ~150 ms)
    → SAFE | BORDERLINE | MEDICAL_REFUSE | EATING_RISK | OUT_OF_SCOPE
          │ refused → 200 refusal response with explanation
          ▼
          │  query_processor.py
    classify_query()   →  SIMPLE | COMPLEX | COMPARISON
          │
          ├─ SIMPLE     → rewrite_query()      →  1 enriched query
          └─ COMPLEX/   → decompose_query()    →  2–3 sub-questions
             COMPARISON
          │
          ▼  retriever.py
    parallel_hybrid_search()
    (embed_query + BM25 sparse, one search per sub-question, asyncio.gather)
          │
          ▼
    rrf_merge()   →  Reciprocal Rank Fusion (k=60)
    apply_diversity_filter()   →  max 2 chunks per source file
          │
          │  0 results → 200 out-of-scope response
          ▼
    _build_assembled_chunks()   →  AssembledChunk list with sub_query_indices
    detect_conflicts()          →  ConflictPair list (heuristic + optional LLM)
          │
          ▼  context assembly strategy
          ├─ SIMPLE      → _format_aggregate()   flat, score-sorted
          ├─ COMPLEX     → _format_chain()        one section per step
          └─ COMPARISON  → _format_compare()      sides + DISPUTED + SHARED PRINCIPLES
          │
          ▼  rag.py
    generate()   →  LLM call (Claude, temperature=0.2, max_tokens=512)
                    JSON output: { "answer": "...", "cited_indices": [...] }
          │
          ▼  guardrails.py  — Layer 3
    filter_output()
    (parse JSON, bounds-check indices, truncate, inject medical disclaimer)
          │
          ▼
    _map_sources()   →  RAGSource list (title, section, excerpt, score)
          │
          ▼
    RAGResponse { answer, in_scope, sources, intent, model, usage }
```

---

## Key design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Chunk boundary | H2 markdown headers | Each section carries one complete concept; arbitrary token cuts break context |
| Embedding model | `text-embedding-3-small` (1536 dims) | Cost-effective, high retrieval quality; dense + sparse stored as named vectors |
| Hybrid search | Dense + BM25 sparse with RRF fusion | Dense handles semantic similarity; sparse handles exact-match keywords; RRF combines both without tuning |
| Query classification | Heuristic pre-filter + LLM fallback (Haiku) | Avoids LLM call for clearly simple/comparison queries; LLM handles ambiguous cases |
| Query rewriting | Applied only for SIMPLE queries ≤ 80 chars | Short queries benefit from abbreviation expansion; long queries already carry enough signal |
| Query decomposition | COMPLEX → steps, COMPARISON → sides | Allows targeted sub-query retrieval rather than one broad search |
| Parallel retrieval | `asyncio.gather` per sub-question | Removes serial latency — 3 sub-questions take the same time as 1 |
| Context assembly | Three strategies by query type | Different structures help the LLM reason appropriately for each question type |
| Conflict detection | Heuristic O(N²) + optional LLM Haiku re-check | Surfaces contradicting chunks rather than silently merging them; LLM pass is skipped when no heuristic candidates are found |
| Source attribution | Server-side index mapping | Prevents hallucinated citations — the LLM returns 1-based indices; the server resolves metadata |
| Ingestion idempotency | Deterministic UUID from `sha256(file + index)` | Re-running the ingest script upserts rather than duplicates existing chunks |
| LLM default | Anthropic Claude | Prompt caching on system + context saves ~70% tokens on repeated questions |
| 3-layer guardrails | Rule filter → intent classifier → output filter | Each layer catches a different risk class at the appropriate cost; the ~0 ms rule filter runs unconditionally and the ~150 ms LLM classifier runs only when risk signals are detected |

---

## File layout

```
backend/app/rag/
├── __init__.py
├── parser.py           ParsedChunk dataclass; parse_document(); parse_all()
├── metadata.py         extract_metadata(); attach_metadata()
├── chunker.py          token-aware split/merge with tiktoken; is_structured_content()
├── embedder.py         build_embed_text(); embed_chunks(); embed_query()
├── sparse.py           build_sparse_vector(); build_sparse_vectors_batch()
├── ingestion.py        chunk_id(); orchestrate parse → chunk → embed → upsert; CLI entry
├── guardrails.py       hard_block_check(); needs_intent_classification(); classify_intent();
│                       parse_llm_output(); contains_medical_advice(); filter_output()
├── query_processor.py  classify_query(); rewrite_query(); decompose_query(); process_query()
├── retriever.py        AssembledChunk; ConflictPair; embed_query(); parallel_hybrid_search();
│                       rrf_merge(); apply_diversity_filter(); detect_conflicts();
│                       assemble_context()  (Aggregate / Chain / Compare strategies)
└── schemas.py          RAGQuery; RAGSource; RAGResponse

backend/app/api/v1/
├── router.py           v1 router aggregator
└── rag.py              POST /api/v1/rag/query  — full pipeline endpoint

backend/tests/mock/
├── test_rag.py         offline tests: Parser, Metadata, Chunker, Embedder, ChunkId,
│                       HybridCollection  (37 cases)
└── test_guardrails.py  guardrail pipeline tests  (49 cases)

backend/tests/live/
└── test_llm_providers.py   end-to-end smoke tests with real API keys

backend/tests/benchmarks/
└── bench_search.py     Qdrant search latency benchmark (dense / sparse / hybrid / filter)
```

---

## API contract

### Request

```json
POST /api/v1/rag/query
{
  "question": "Is PPL or Upper/Lower better for an intermediate lifter?",
  "max_sources": 5
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | `string` | 3–1000 characters |
| `max_sources` | `integer` | 1–5, default 5 |

### Response

```json
{
  "answer": "Both splits can work well for intermediate lifters... [1][2]",
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

---

## Open questions

1. **Score threshold calibration** — `0.35` is an estimate. Validate against 20–30
   labelled questions (in-scope + out-of-scope) before shipping.
2. **Conflict detection precision** — The heuristic contradiction patterns (`never / always`,
   `avoid / recommended`) may produce false positives for nuanced strength-training content.
   Evaluate with a labelled conflict set before enabling the LLM re-check in production.
3. **Supplemental documents** — Candidates for additional knowledge-base content:
   TDEE/calorie guide, sleep & recovery, beginner program templates.
   Any additions must be logged in `docs/system/knowledge-base-additions.md`.
4. **Embedding model lock-in** — The Qdrant collection dimension is tied to the model.
   Changing providers requires recreating the collection and re-embedding all chunks.
5. **Re-ingestion on doc changes** — Upsert handles content updates to existing chunks.
   Structural changes (document split/merge) require a full delete-and-reingest per collection.
