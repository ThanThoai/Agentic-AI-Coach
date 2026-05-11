# Feature 1 — RAG Ingestion Pipeline: Test Scenarios

**Modules:** `app/rag/parser.py`, `app/rag/metadata.py`, `app/rag/chunker.py`,
`app/rag/embedder.py`, `app/rag/ingestion.py`, `app/vectordb/qdrant.py`
**Test file:** `backend/tests/mock/test_rag.py`
**Last updated:** 2026-05-11

---

## Pipeline overview

```
Markdown files (knowledge-base/)
  │
  ▼
Parser           → list[RawChunk]           H1/H2 splitting, source metadata
  │
  ▼
Metadata         → list[RawChunk]           topic_type, difficulty, tags enrichment
  │
  ▼
Chunker          → list[RawChunk]           split/merge by token count
  │
  ▼
Embedder         → list[(RawChunk, vector)] dense vectors via LLM provider
  │
  ▼
Ingestion        → Qdrant upsert            deterministic UUID, hybrid sparse+dense points
```

All tests use `MockLLMProvider` for embeddings and Qdrant in-memory mode — no external calls.

---

## TestParser — 9 tests

**Functions tested:** `parse_document(path)`, `parse_all(directory)`

### Scenario: Section splitting

| Test | Input | Expected |
|------|-------|----------|
| `test_parse_document_sections` | File with 3 H2 headers | Returns exactly 3 chunks whose `section_title` matches the H2 text |
| `test_parse_document_doc_title` | Any multi-section file | Every chunk carries the H1 title as `doc_title` |
| `test_parse_document_source_file` | Any file | Every chunk carries the filename (not the full path) as `source_file` |
| `test_parse_document_chunk_indices_sequential` | File with 3 H2 headers | Chunk indices are `["0", "1", "2"]` in order |
| `test_parse_all_returns_all_chunks` | Directory with 2 files | Both `source_file` names appear in the output |

### Scenario: Edge cases in file structure

| Test | Input | Expected |
|------|-------|----------|
| `test_parse_document_no_h2_fallback` | File with H1 but no H2 | Returns exactly 1 chunk; `section_title == doc_title` |
| `test_parse_document_content_before_first_h2` | Preamble text before the first `##` | A synthetic `"Overview"` section is created from the preamble |
| `test_parse_document_empty_h2_skipped` | One H2 with empty body, one with content | Empty section does not appear; the content section does |
| `test_parse_document_h3_stays_inside_h2` | H3 nested under an H2 | H3 heading and its body appear inside the parent H2 chunk, not as a separate chunk |

**Why this matters:** The parser must not create empty chunks (which would pollute the index)
and must preserve H3 nesting within H2 to keep context intact for retrieval.

---

## TestMetadata — 5 tests

**Functions tested:** `extract_metadata(source_file)`, `attach_metadata(chunk, meta)`

### Scenario: Metadata derived from filename

| Test | Input `source_file` | Expected fields |
|------|---------------------|-----------------|
| `test_extract_metadata_known_file` | `"01-bench-press.md"` | `topic_type="technique"`, `"chest"` and `"compound"` in `tags` |
| `test_extract_metadata_difficulty_default` | Any technique file | `difficulty == ["beginner", "intermediate", "advanced"]` (all levels) |
| `test_extract_metadata_difficulty_override` | `"14-workout-split-ppl.md"` | `difficulty` contains `"advanced"`, does not contain `"beginner"` |
| `test_extract_metadata_programming` | `"08-progressive-overload.md"` | `topic_type == "programming"` |
| `test_extract_metadata_unknown_file_fallback` | `"99-unknown-topic.md"` | Default difficulty; `topic_type == "technique"` — no crash |

### Scenario: Attaching metadata to a chunk

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_attach_metadata_mutates_chunk` | `attach_metadata(chunk, meta)` | Mutates the chunk in-place and returns the same object |

**Why metadata matters:** `build_embed_text()` uses metadata fields to build the embedding
prefix. Missing metadata degrades retrieval quality. The unknown-file fallback ensures the
pipeline does not crash when new documents are added before the metadata map is updated.

---

## TestChunker — 9 tests

**Functions tested:** `process_chunks(chunks)`, `is_structured_content(text)`
**Token thresholds:** `MIN=50`, `MAX=512`, `OVERLAP=64`

### Scenario: Three size paths

| Test | Input | Expected |
|------|-------|----------|
| `test_normal_chunk_passes_through` | 200-token chunk | Returned unchanged; `chunk_index` stays `"0"` |
| `test_oversized_chunk_is_split` | 600-token chunk | Split into `≥ 2` sub-chunks indexed `"0.0"`, `"0.1"` |
| `test_split_chunks_respect_max_tokens` | 700-token chunk | Every sub-chunk is `≤ 512` tokens |

### Scenario: Short-chunk merging

| Test | Input | Expected |
|------|-------|----------|
| `test_short_chunk_merged_with_next` | 30-token chunk followed by 100-token chunk | Output is 1 merged chunk; `section_title` contains both original titles |
| `test_last_short_chunk_merged_with_previous` | 100-token chunk followed by 20-token chunk | Merged backward into previous chunk; output is 1 chunk |
| `test_single_short_chunk_kept` | Only one 20-token chunk in the document | Kept as-is (no following or previous chunk to merge with) |

**Why backward merge:** The last chunk in a document has no following chunk, so it merges
backward. Dropping it would cause silent content loss.

### Scenario: Overlap between split sub-chunks

| Test | Input | Expected |
|------|-------|----------|
| `test_overlap_in_split_chunks` | 600-token chunk split into two | The last 10 tokens of sub-chunk `0` appear again at the start of sub-chunk `1` |

**Why overlap matters:** Without it, a sentence split exactly at the boundary loses context.
Overlap ensures the retriever can match queries that reference content near chunk boundaries.

### Scenario: Structured content detection

| Test | Input | Expected |
|------|-------|----------|
| `test_is_structured_content_table` | Text where 60%+ of lines are `\| ... \|` table rows | `True` — structured content is not merged to preserve table integrity |
| `test_is_structured_content_normal` | Plain prose paragraph | `False` |

---

## TestEmbedder — 6 tests

**Functions tested:** `build_embed_text(chunk)`, `embed_chunks(chunks, provider)`, `embed_query(question, provider)`

### Scenario: Embed text construction with prefix

| Test | Input | Expected |
|------|-------|----------|
| `test_build_embed_text_contains_prefix` | Chunk with known `doc_title`, `section_title`, `topic_type`, `tags` | Prefix line contains all four fields in the correct format |
| `test_build_embed_text_contains_chunk_body` | Chunk with body text | The original body appears in the embed text |
| `test_build_embed_text_prefix_before_body` | Any chunk | The prefix ends before the first `\n\n`; the body starts after |

**Key invariant:** `embed_text ≠ stored_text` — the prefix is added only for the embedding
call, never stored in the Qdrant payload. Tests verify the prefix appears in
`build_embed_text()` output but the chunk's `.text` field is never modified.

### Scenario: Provider calls and batching

| Test | Input | Expected |
|------|-------|----------|
| `test_embed_chunks_calls_provider` | 3 chunks, `MockLLMProvider` | Returns 3 `(chunk, vector)` pairs; each vector is a non-empty list |
| `test_embed_chunks_batches_correctly` | 75 chunks, `batch_size=50` | All 75 pairs returned correctly across 2 batches |
| `test_embed_query_returns_vector` | Single question string | Returns a non-empty `list[float]` |

---

## TestChunkId — 4 tests

**Function tested:** `chunk_id(source_file, chunk_index)` in `app/rag/ingestion.py`

### Scenario: Determinism

| Test | Scenario | Expected |
|------|----------|----------|
| `test_chunk_id_deterministic` | Same `source_file` + `chunk_index` called twice | Both calls return the same UUID string |
| `test_chunk_id_different_files` | Same index, different filenames | Different UUIDs |
| `test_chunk_id_different_indices` | Same file, different indices | Different UUIDs |
| `test_chunk_id_is_valid_uuid` | Any valid input | `uuid.UUID(result)` succeeds; `str(parsed) == result` |

**Why deterministic IDs matter:** Re-running the ingestion script must upsert rather than
duplicate existing chunks. The ID is derived from `sha256(source_file + "::" + chunk_index)`,
guaranteeing the same chunk always maps to the same Qdrant point ID.

---

## TestHybridCollection — 4 tests

**Functions tested:** `ensure_collection_hybrid()`, `upsert_hybrid()`, `hybrid_search()`
**Infrastructure:** Qdrant in-memory mode

### Scenario: Collection management

| Test | Scenario | Expected |
|------|----------|----------|
| `test_ensure_collection_hybrid_idempotent` | `ensure_collection_hybrid()` called twice | No exception on second call; collection exists with `"dense"` and `"sparse"` named vectors |
| `test_upsert_and_count` | Insert 1 hybrid point | `count() == 1` after upsert |
| `test_upsert_idempotent` | Insert the same point ID twice with a different payload | `count()` remains 1 (upsert semantics, not append) |

### Scenario: Hybrid search with RRF fusion

| Test | Scenario | Expected |
|------|----------|----------|
| `test_hybrid_search_returns_results` | 2 points; query vector is close to point #1 | Top result payload matches point #1 (`source_file == "01-bench-press.md"`) |

**RRF mechanism:** `hybrid_search()` uses `Prefetch` (dense top-20, sparse top-20) followed
by `FusionQuery(Fusion.RRF)`. The in-memory test confirms the fusion pipeline returns the
correct top-1 when the dense signal clearly favours one point over the other.

---

## Running these tests

```bash
# All ingestion tests
uv run pytest tests/mock/test_rag.py -v

# By class
uv run pytest tests/mock/test_rag.py::TestParser -v
uv run pytest tests/mock/test_rag.py::TestMetadata -v
uv run pytest tests/mock/test_rag.py::TestChunker -v
uv run pytest tests/mock/test_rag.py::TestEmbedder -v
uv run pytest tests/mock/test_rag.py::TestChunkId -v
uv run pytest tests/mock/test_rag.py::TestHybridCollection -v

# Single test
uv run pytest tests/mock/test_rag.py::TestChunker::test_overlap_in_split_chunks -v
```

---

## See also

- `docs/features/feature_1/chunking-embedding.md` — full spec for parser, chunker, and embedder
- `docs/system/vector-database.md` — Qdrant collection schema and named-vector layout
- `docs/system/testing/feature-1-query-retrieval.md` — downstream usage of these ingested chunks
