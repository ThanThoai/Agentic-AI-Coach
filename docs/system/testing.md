# Testing Guide

**Last updated:** 2026-05-11

---

## Overview

The backend test suite is split into two tiers:

| Tier | Location | When to run | External dependencies |
|------|----------|-------------|----------------------|
| **Mock** (default) | `tests/mock/` | Every commit, CI | None — all I/O intercepted |
| **Live** | `tests/live/` | Pre-release, on demand | Real API keys + network |

```bash
# Run mock tests only (default)
uv run pytest

# Run live tests explicitly
uv run pytest -m live
```

The root `tests/conftest.py` loads `.env.test` (or falls back to `.env`) before any test
imports occur, so `Settings()` initialises cleanly without requiring environment variables
to be set in the shell.

---

## Mock test files

### `tests/mock/test_qdrant.py`

Tests the `QdrantVectorDB` wrapper (`app/vectordb/qdrant.py`) using Qdrant's
**in-memory mode** — no real server required.

#### `test_upsert_and_search`

**Scenario:** Insert two vectors with distinct payloads, query with a vector identical
to the first point.

**Checks:**
- `upsert()` returns a list of IDs with the same length as input
- `search()` returns at least one result
- The top result has `score > 0.9` (near-perfect cosine match)

**Why it matters:** Verifies the happy path of the write → read cycle. If this fails,
nothing else in the RAG pipeline will work.

---

#### `test_search_with_filter`

**Scenario:** Insert two points with identical vectors but different `type` payloads
(`"knowledge"` vs `"workout"`). Search with `filter_by={"type": "knowledge"}`.

**Checks:**
- All returned results have `payload["type"] == "knowledge"`
- The `"workout"` point is not returned despite having the same vector

**Why it matters:** Validates `filter_by` payload filtering, which the RAG retriever
uses to narrow searches by `topic_type` or `difficulty`.

---

#### `test_delete`

**Scenario:** Insert one point, record count, delete it, check count again.

**Checks:**
- `count_after == count_before - 1`

**Why it matters:** Ensures the `delete()` method works correctly for collection
management (e.g., re-ingestion workflows that remove stale chunks).

---

#### `test_count_empty`

**Scenario:** Query `count()` on a freshly created collection with no points.

**Checks:**
- `count == 0`

**Why it matters:** Baseline sanity check — verifies collection creation and
the count API are functional.

---

### `tests/mock/test_rag.py`

End-to-end offline tests for the ingestion pipeline
(`parser → metadata → chunker → embedder → ingestion`).
All embedding API calls use `MockLLMProvider`; Qdrant uses in-memory mode.

---

#### `TestParser` — 9 tests

Tests `app/rag/parser.py`: `parse_document()`, `parse_all()`.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_parse_document_sections` | File with 3 H2 headers | Returns exactly 3 chunks with the correct `section_title` values |
| `test_parse_document_doc_title` | Any multi-section file | Every chunk carries the H1 title as `doc_title` |
| `test_parse_document_source_file` | Any file | Every chunk carries the filename (not the full path) as `source_file` |
| `test_parse_document_chunk_indices_sequential` | File with 3 H2 headers | Chunk indices are `["0", "1", "2"]` in order |
| `test_parse_all_returns_all_chunks` | Directory with 2 files | Both `source_file` names appear in the output |
| `test_parse_document_no_h2_fallback` | File with H1 but no H2 | Returns exactly 1 chunk with `section_title == doc_title` |
| `test_parse_document_content_before_first_h2` | Preamble text before the first `##` | An `"Overview"` synthetic section is created from the preamble |
| `test_parse_document_empty_h2_skipped` | One H2 with empty body, one with content | The empty section does not appear; the content section does |
| `test_parse_document_h3_stays_inside_h2` | H3 nested under an H2 | The H3 heading and its body appear inside the parent H2 chunk, not as a separate chunk |

**Edge cases covered:** pre-H2 preamble, no-H2 fallback, empty sections, H3 nesting.

---

#### `TestMetadata` — 5 tests

Tests `app/rag/metadata.py`: `extract_metadata()`, `attach_metadata()`.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_extract_metadata_known_file` | `source_file = "01-bench-press.md"` | `topic_type == "technique"`, `"chest"` and `"compound"` in `tags` |
| `test_extract_metadata_difficulty_default` | Any exercise technique file | `difficulty == ["beginner", "intermediate", "advanced"]` (default all-levels) |
| `test_extract_metadata_difficulty_override` | `"14-workout-split-ppl.md"` | `difficulty` contains `"advanced"` but not `"beginner"` |
| `test_extract_metadata_programming` | `"08-progressive-overload.md"` | `topic_type == "programming"` |
| `test_extract_metadata_unknown_file_fallback` | `"99-unknown-topic.md"` | Returns default difficulty and `topic_type == "technique"` (safe fallback, no crash) |
| `test_attach_metadata_mutates_chunk` | `attach_metadata(chunk, meta)` | Mutates the chunk in-place and returns the same object |

**Edge cases covered:** filename slug matching, difficulty override rules, unknown
document graceful fallback.

---

#### `TestChunker` — 9 tests

Tests `app/rag/chunker.py`: `process_chunks()`, `is_structured_content()`.

Token thresholds: `MIN=50`, `MAX=512`, `OVERLAP=64`.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_normal_chunk_passes_through` | 200-token chunk | Returned unchanged; `chunk_index` stays `"0"` |
| `test_oversized_chunk_is_split` | 600-token chunk | Split into `≥ 2` sub-chunks indexed `"0.0"`, `"0.1"` |
| `test_split_chunks_respect_max_tokens` | 700-token chunk | Every sub-chunk is `≤ 512` tokens |
| `test_short_chunk_merged_with_next` | 30-token chunk followed by 100-token chunk | Output is 1 merged chunk; `section_title` contains both original titles |
| `test_last_short_chunk_merged_with_previous` | 100-token chunk followed by 20-token chunk | Merged backward; output is 1 chunk |
| `test_single_short_chunk_kept` | Only one 20-token chunk in the document | Not discarded — kept as-is (content loss prevention) |
| `test_is_structured_content_table` | Text where 60%+ of lines are `\| ... \|` table rows | Returns `True` |
| `test_is_structured_content_normal` | Plain prose paragraph | Returns `False` |
| `test_overlap_in_split_chunks` | 600-token chunk split into two | Last 10 tokens of sub-chunk `0` also appear at the start of sub-chunk `1` |

**Edge cases covered:** three distinct size paths (short/normal/long), last-chunk
backward merge, single-chunk document, structured content detection, overlap
continuity.

---

#### `TestEmbedder` — 6 tests

Tests `app/rag/embedder.py`: `build_embed_text()`, `embed_chunks()`, `embed_query()`.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_build_embed_text_contains_prefix` | Chunk with known `doc_title`, `section_title`, `topic_type`, `tags` | The prefix line contains all four fields in the correct format |
| `test_build_embed_text_contains_chunk_body` | Chunk with body text | The original chunk body appears in the embed text |
| `test_build_embed_text_prefix_before_body` | Any chunk | The prefix ends before the first `\n\n`; the body starts after |
| `test_embed_chunks_calls_provider` | 3 chunks, `MockLLMProvider` | Returns 3 `(chunk, vector)` pairs; each vector is a non-empty list |
| `test_embed_chunks_batches_correctly` | 75 chunks, `batch_size=50` | All 75 pairs returned correctly across 2 batches |
| `test_embed_query_returns_vector` | Single question string | Returns a non-empty `list[float]` |

**Key invariant tested:** `embed_text ≠ stored_text` — the prefix is added only
for the embedding call, not stored in the payload. The tests verify the prefix is
present in `build_embed_text()` output but that the chunk's `.text` field is
never modified.

---

#### `TestChunkId` — 4 tests

Tests the `chunk_id()` function in `app/rag/ingestion.py`.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_chunk_id_deterministic` | Same `source_file` + `chunk_index` called twice | Both calls return the same UUID string |
| `test_chunk_id_different_files` | Same index, different filenames | Different UUIDs |
| `test_chunk_id_different_indices` | Same file, different indices | Different UUIDs |
| `test_chunk_id_is_valid_uuid` | Any valid input | `uuid.UUID(result)` succeeds; `str(parsed) == result` |

**Why deterministic IDs matter:** Re-running the ingestion script must upsert
(not duplicate) existing chunks. A deterministic ID derived from
`sha256(source_file + "::" + chunk_index)` guarantees that the same chunk
always maps to the same Qdrant point ID.

---

#### `TestHybridCollection` — 4 tests

Tests the hybrid collection methods added to `QdrantVectorDB`
(`ensure_collection_hybrid`, `upsert_hybrid`, `hybrid_search`).
Uses Qdrant in-memory mode.

| Test | Scenario | What it checks |
|------|----------|----------------|
| `test_ensure_collection_hybrid_idempotent` | `ensure_collection_hybrid()` called twice | Does not raise on second call; collection exists with `"dense"` + `"sparse"` named vectors |
| `test_upsert_and_count` | Insert 1 hybrid point | `count() == 1` after upsert |
| `test_upsert_idempotent` | Insert same point ID twice with different payload | `count()` remains 1 (upsert semantics, not insert) |
| `test_hybrid_search_returns_results` | 2 points inserted; query vector similar to point #1 | Top result payload matches point #1 (`source_file == "01-bench-press.md"`) |

**RRF fusion:** `hybrid_search()` uses `Prefetch` (dense top-20, sparse top-20)
followed by `FusionQuery(Fusion.RRF)`. The in-memory test verifies the fusion
pipeline returns the correct top-1 when the dense signal clearly favours one point
over the other.

---

## Running specific test groups

```bash
# All mock tests (default)
uv run pytest tests/mock/

# Only Qdrant tests
uv run pytest tests/mock/test_qdrant.py -v

# Only RAG tests
uv run pytest tests/mock/test_rag.py -v

# Only a specific class
uv run pytest tests/mock/test_rag.py::TestChunker -v

# Only a specific test
uv run pytest tests/mock/test_rag.py::TestChunker::test_overlap_in_split_chunks -v

# All tests including live (requires .env with real keys)
uv run pytest -m live
```

---

## Adding new tests

- Mock tests go in `tests/mock/`. Use `MockLLMProvider` from `tests/mock/conftest.py`
  for any test that calls an LLM.
- Live tests go in `tests/live/`. Use the provider fixtures from
  `tests/live/conftest.py`; add `@pytest.mark.live` to the test.
- New domain fixtures belong in `tests/mock/conftest.py` (shared across mock tests).
- Do not call `Settings()` directly in test files — the root conftest loads `.env.test`
  so settings are always available via the normal `from app.core.config import settings`
  import.

---

## Search latency benchmark

**Script:** `backend/tests/benchmarks/bench_search.py`

Measures Qdrant query latency in isolation — embedding API calls are **not** included.
Query vectors are pre-computed once before timing starts.

```bash
# Quick run — all modes, 104 points, 100 queries each
uv run python -m tests.benchmarks.bench_search

# Full run with BM25 CPU timing
uv run python -m tests.benchmarks.bench_search --n-queries 300 --warmup 30 --include-bm25

# Against a real Qdrant server
uv run python -m tests.benchmarks.bench_search --url http://localhost:6333

# Single mode
uv run python -m tests.benchmarks.bench_search --mode dense
uv run python -m tests.benchmarks.bench_search --mode sparse
uv run python -m tests.benchmarks.bench_search --mode hybrid
```

### Benchmark modes

| Mode | What is measured |
|------|-----------------|
| `bm25-cpu` | Local BM25 sparse vector computation (fastembed, no network) |
| `dense` | `query_points` with named dense vector |
| `sparse` | `query_points` with named sparse (BM25) vector |
| `hybrid (RRF)` | `Prefetch[dense, sparse]` + `FusionQuery(RRF)` |
| `hybrid + filter` | Hybrid with payload filter `topic_type == technique` |

### Benchmark results

**Environment:** Qdrant in-memory, 104 hybrid points (realistic fixture), 300 queries per mode,
30 warmup iterations discarded, `limit=5`, `prefetch=20`, `vector_size=1536`.
Measured on: Linux x86-64, single process, asyncio, no concurrency.

```
uv run python -m tests.benchmarks.bench_search \
  --n-points 104 --n-queries 300 --warmup 30 --include-bm25
```

| Mode | n | min | p50 | p90 | p99 | max | RPS |
|------|---|-----|-----|-----|-----|-----|-----|
| bm25-cpu | 300 | 0.02 ms | 0.02 ms | 0.02 ms | 0.03 ms | 0.05 ms | 54,293 |
| dense | 300 | 1.58 ms | 1.65 ms | 2.00 ms | 2.59 ms | 2.89 ms | 578 |
| sparse | 300 | 3.06 ms | 3.18 ms | 3.70 ms | 4.61 ms | 4.71 ms | 303 |
| hybrid (RRF) | 300 | 7.40 ms | 7.73 ms | 8.78 ms | 10.43 ms | 11.33 ms | 126 |
| hybrid + filter | 300 | 8.84 ms | 9.55 ms | 10.81 ms | 12.25 ms | 59.83 ms | 100 |

### Interpreting the numbers

**BM25 CPU (0.02 ms / 54k RPS)**
Sparse vector computation is negligible — it's a local tokenisation + TF-IDF scoring step with no
network round-trip. The fastembed `Qdrant/bm25` model runs entirely on CPU and costs less than
a single `time.sleep(0)` call per query.

**Dense (p50 = 1.65 ms)**
Single named-vector search. In-memory Qdrant skips network I/O, so this baseline represents
the HNSW graph traversal cost only. On a remote Qdrant Cloud instance, expect +5–15 ms
network overhead on top of this.

**Sparse (p50 = 3.18 ms, ~2× dense)**
BM25 sparse indices can have up to 150 non-zero terms per query. Qdrant must resolve the
inverted index for each term, making it slower than a single dense ANN lookup. The overhead
is predictable and bounded — it scales with vocabulary hit count, not corpus size.

**Hybrid RRF (p50 = 7.73 ms, ~4.7× dense)**
Two prefetch searches (dense + sparse, 20 results each) followed by RRF rank fusion.
The latency is roughly `dense + sparse + fusion_overhead`, not `dense × 2`. The fusion
step itself is O(prefetch_limit) and adds < 1 ms.

**Hybrid + filter (p50 = 9.55 ms)**
Applying a payload filter to each prefetch adds ~1–2 ms over unfiltered hybrid because
Qdrant must intersect the filter bitmap with the HNSW/inverted-index results. The p99
spike (12.25 ms) reflects occasional index cold-starts for smaller filtered subsets.

### Production latency estimate

Adding real-world network latency to a Qdrant Cloud instance (~5–15 ms RTT) and the
embedding API call (OpenAI `text-embedding-3-small` ~100–200 ms):

| Step | Estimated time |
|------|----------------|
| BM25 sparse vector (local) | ~0.02 ms |
| Dense embedding API call | ~100–200 ms |
| Qdrant hybrid search (remote) | ~13–25 ms |
| **Total query latency (p50)** | **~115–225 ms** |

The embedding call dominates. To reduce it: use a local embedding model, or cache
repeated queries (e.g. Redis with a 1h TTL on the question hash).

---

## See also

- `docs/system/vector-database.md` — Qdrant collection schema and client usage
- `docs/features/feature_1/chunking-embedding.md` — full spec for the RAG pipeline
- `backend/tests/benchmarks/bench_search.py` — latency benchmark script
