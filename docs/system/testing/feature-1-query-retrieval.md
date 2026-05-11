# Feature 1 — Query Processing & Retrieval: Test Scenarios

**Modules:** `app/rag/query_processor.py`, `app/rag/retriever.py`, `app/api/v1/rag.py`
**Test files:** *(pending — see §Planned tests below)*
**Last updated:** 2026-05-11

---

## Pipeline overview

```
POST /api/v1/rag/query  { question, max_sources }
  │
  ▼
Guardrails (Layer 1 + 2)         ← see feature-1-guardrails.md
  │
  ▼
QueryProcessor
  ├─ classify_query()             → QueryType: SIMPLE | COMPLEX | COMPARISON
  ├─ rewrite_query()              → enriched query string       (SIMPLE only)
  └─ decompose_query()            → list[sub_questions]         (COMPLEX / COMPARISON)
  │
  ▼
Retriever
  ├─ embed_query()                → dense vector
  ├─ parallel_hybrid_search()     → list[list[SearchResult]]    (one per sub-question)
  ├─ rrf_merge()                  → merged list[SearchResult]
  └─ apply_diversity_filter()     → per-source capped list
  │
  ▼
ContextAssembler
  ├─ _build_assembled_chunks()    → list[AssembledChunk] with sub_query_indices
  ├─ detect_conflicts()           → list[ConflictPair]
  └─ strategy dispatch:
       SIMPLE     → _format_aggregate()   flat relevance-sorted list
       COMPLEX    → _format_chain()       one section per sub-question step
       COMPARISON → _format_compare()     grouped by side + DISPUTED section
  │
  ▼
Generator
  └─ generate()                   → LLMResponse with JSON { answer, cited_indices }
  │
  ▼
Guardrails (Layer 3)             ← filter_output()
  │
  ▼
RAGResponse { answer, in_scope, sources, intent, model, usage }
```

---

## QueryProcessor — Planned tests

> **Status: 🔲 Pending** — no test file yet. The scenarios below are the spec for writing tests.

### `classify_query_heuristic(question)`

| Scenario | Input | Expected |
|----------|-------|----------|
| Clear comparison signal | `"PPL vs Upper/Lower — which is better?"` | `"COMPARISON"` |
| "Better than" signal | `"Is deadlift better than Romanian deadlift?"` | `"COMPARISON"` |
| Complexity signal + length > 120 | Question > 120 chars containing `"and how"` | `"COMPLEX"` |
| Complexity signal but short | Question < 120 chars with `"and also"` | `None` (needs LLM) |
| Short question, no signal | `"How many sets per week for chest?"` (≤ 80 chars) | `"SIMPLE"` |
| Medium length, no signal | 81–120 chars, no keyword match | `None` (needs LLM) |

### `rewrite_query(question, provider)`

| Scenario | Input | Expected |
|----------|-------|----------|
| Short question with abbreviation | `"OHP form tips"` | Output contains `"overhead press"` or equivalent expansion |
| Question > 80 chars | Long question (> 80 chars) | Returns the original unchanged (skips rewrite) |
| Provider returns empty string | Provider yields `""` | Falls back to original question |
| Provider returns > 300 chars | Provider yields 301-char string | Falls back to original question |

### `decompose_query(question, provider)`

| Scenario | Input | Expected |
|----------|-------|----------|
| COMPLEX with 2 sub-topics | `"How to structure PPL and what intensity for hypertrophy?"` | 2 sub-questions, each independently answerable |
| COMPARISON with 2 options | `"Creatine vs protein powder — which first?"` | 2 sub-questions, one per option |
| LLM parse error | Provider returns invalid JSON | Falls back to `[question]` (1 sub-question) |
| LLM returns > 3 sub-questions | `{"sub_questions": ["a","b","c","d"]}` | Falls back to `[question]` |

### `process_query(question, provider)`

| Scenario | Input | Expected tuple |
|----------|-------|----------------|
| SIMPLE | `"How many sets for chest?"` | `("SIMPLE", [rewritten_query])` |
| COMPLEX | Multi-part question | `("COMPLEX", [sub_q1, sub_q2])` |
| COMPARISON | "vs" question | `("COMPARISON", [side_a_q, side_b_q])` |

---

## Retriever — Planned tests

> **Status: 🔲 Pending**

### `rrf_merge(results_per_query, k=60)`

| Scenario | Input | Expected |
|----------|-------|----------|
| Same document appears in 2 queries | Doc A rank 1 in query 1 and rank 1 in query 2 | Doc A score = `1/(60+1) + 1/(60+1)` ≈ 0.0328; Doc A is top result |
| Document appears in only 1 query | Doc B rank 2 in query 1 only | Doc B score = `1/(60+2)` ≈ 0.0161 |
| Deduplication | Same `source_file` + `section_title` in both query lists | Appears once in output with combined score |
| Score threshold | All results below `score=0.35` | Returns empty list |

### `apply_diversity_filter(chunks, max_per_source=2)`

| Scenario | Input | Expected |
|----------|-------|----------|
| 3 chunks from the same source file | 3 chunks from `"01-bench-press.md"` | Only the top 2 by score are kept |
| Chunks from multiple sources | 2 from file A, 2 from file B | All 4 are kept |
| `max_per_source=1` | 5 chunks, each from a different source | All 5 are kept |

### `assemble_context()` — Aggregate strategy (SIMPLE)

| Scenario | Input | Expected |
|----------|-------|----------|
| Happy path | 3 AssembledChunks, no conflicts | Context opens with `[CONTEXT — AGGREGATED]`; 3 numbered sections |
| Token budget exceeded | Chunks exceed 1200 tokens | Only chunks that fit within the budget are included |
| Empty chunk list | `[]` | Returns empty string |

### `assemble_context()` — Chain strategy (COMPLEX)

| Scenario | Input | Expected |
|----------|-------|----------|
| 2 sub-questions | Chunks tagged with `sub_query_indices` | Context contains `=== STEP 1: <label> ===` and `=== STEP 2: <label> ===` |
| Chunk spans 2 sub-queries | `sub_query_indices = {0, 1}` | Chunk is placed under the `primary_sub_query` step |

### `assemble_context()` — Compare strategy (COMPARISON)

| Scenario | Input | Expected |
|----------|-------|----------|
| 2 sides, no conflict | Sub-q 0 = Side A, sub-q 1 = Side B | Context contains `=== SIDE A ===` and `=== SIDE B ===` |
| Cross-side conflict detected | Chunk A (sub-q 0) and Chunk B (sub-q 1) contradict each other | Both are moved into `=== DISPUTED ===`, removed from their side sections |
| Shared principles | Chunk with `sub_query_indices = {0, 1}` | Placed in `=== SHARED PRINCIPLES ===` |

### `detect_conflicts_heuristic(chunks)`

| Scenario | Input | Expected |
|----------|-------|----------|
| Contradiction keyword | Chunk A: `"always do X"`, Chunk B: `"never do X"` | `ConflictPair` returned |
| No contradiction | 3 chunks on the same topic, no opposing claims | `[]` |
| Same source file | 2 chunks from the same file with opposing language | Not flagged (same-source is not treated as conflict) |

---

## RAG Endpoint — Planned tests

> **Status: 🔲 Pending**

### `POST /api/v1/rag/query` — Integration flow

| Scenario | Input | Expected response |
|----------|-------|-------------------|
| Off-topic query (Layer 1 block) | `{"question": "what is the weather?"}` | `in_scope=False`; `answer` contains `RESPONSE_OUT_OF_SCOPE` |
| Medical query (Layer 2 block) | Question containing `"ACL surgery"` + LLM returns `MEDICAL_REFUSE` | `in_scope=False`; `answer` contains `RESPONSE_MEDICAL_REFUSE` |
| Eating risk (Layer 2 block) | Extreme diet question + LLM returns `EATING_RISK` | `in_scope=False`; `answer` contains `RESPONSE_EATING_RISK` |
| Borderline with disclaimer | LLM returns `BORDERLINE` + retrieval succeeds | `in_scope=True`; `answer` ends with `BORDERLINE_DISCLAIMER` |
| No retrieval results | Valid question; Qdrant returns `[]` | `in_scope=False`; `answer` contains `OUT_OF_SCOPE_MESSAGE` |
| Happy path SIMPLE | `{"question": "How many sets for hypertrophy?"}` | `in_scope=True`; `sources` non-empty; `model` is set |
| Happy path COMPLEX | Multi-part question | `in_scope=True`; `intent == "COMPLEX"` |
| Happy path COMPARISON | "vs" question | `in_scope=True`; `intent == "COMPARISON"` |
| `max_sources` respected | `{"question": "...", "max_sources": 3}` | `len(sources) ≤ 3` |
| Out-of-bounds cited indices | LLM returns `cited_indices: [0, 99]` | Source list is empty or contains only valid indices |

### Error handling

| Scenario | Condition | Expected |
|----------|-----------|----------|
| Qdrant unavailable | Qdrant raises an exception | HTTP 500 via unhandled exception handler |
| LLM timeout | LLM provider raises a timeout error | HTTP 504 or 500 depending on domain exception mapping |
| Question too short | `{"question": "x"}` (< 3 chars) | HTTP 422 from Pydantic validation |
| Unknown request field | `{"question": "...", "unknown": 1}` | HTTP 422 (`extra="forbid"` on `RAGQuery`) |

---

## Starter code for QueryProcessor tests

```python
# tests/mock/test_query_processor.py

import pytest
from app.rag.query_processor import (
    classify_query_heuristic,
    classify_query,
    rewrite_query,
    decompose_query,
    process_query,
)
from tests.mock.conftest import MockLLMProvider


class TestClassifyQueryHeuristic:
    def test_comparison_vs(self):
        assert classify_query_heuristic("PPL vs Upper/Lower which is better") == "COMPARISON"

    def test_simple_short(self):
        assert classify_query_heuristic("How many sets for chest?") == "SIMPLE"

    def test_returns_none_for_ambiguous(self):
        # 81–120 chars, no comparison/complexity signal — needs LLM
        question = "What is the best approach to training for general fitness goals in life?"
        assert classify_query_heuristic(question) is None


class TestRewriteQuery:
    @pytest.mark.asyncio
    async def test_skips_long_query(self):
        long_q = "a" * 81
        result = await rewrite_query(long_q, MockLLMProvider())
        assert result == long_q  # returned unchanged

    @pytest.mark.asyncio
    async def test_rewrites_short_query(self):
        from tests.mock.test_guardrails import ControlledMockLLMProvider
        provider = ControlledMockLLMProvider("overhead press barbell form shoulder mechanics")
        result = await rewrite_query("OHP form tips", provider)
        assert "overhead press" in result.lower()
```

---

## Running (once implemented)

```bash
# Query processor tests
uv run pytest tests/mock/test_query_processor.py -v

# Retriever tests
uv run pytest tests/mock/test_retriever.py -v

# RAG endpoint tests
uv run pytest tests/mock/test_rag_endpoint.py -v

# Full feature 1 suite
uv run pytest tests/mock/ -v
```

---

## See also

- `docs/features/feature_1/retrieval-generation.md` — full design spec: query processor, retriever, context assembly strategies, conflict detection
- `docs/system/testing/feature-1-guardrails.md` — guardrail tests (Layer 1/2/3)
- `docs/system/testing/feature-1-ingestion.md` — upstream ingestion pipeline tests
- `docs/system/testing/benchmarks.md` — Qdrant search latency benchmark
