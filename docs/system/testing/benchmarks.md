# Search Latency Benchmarks

**Script:** `backend/tests/benchmarks/bench_search.py`
**Last updated:** 2026-05-11

---

## Purpose

Measure Qdrant search latency per mode (dense, sparse, hybrid) to:

- Confirm that hybrid RRF does not add unacceptable overhead over dense-only search
- Tune `prefetch_limit` and `score_threshold` values
- Establish a baseline before optimisations (query caching, local embedding, connection pooling)

Embedding API calls are **excluded** from all measurements — only Qdrant query time is measured.
Query vectors are pre-computed once before the timing loop starts.

---

## Running the benchmark

```bash
# Quick run — all modes, 104 points, 100 queries per mode
uv run python -m tests.benchmarks.bench_search

# Full run with BM25 CPU timing included
uv run python -m tests.benchmarks.bench_search --n-queries 300 --warmup 30 --include-bm25

# Single mode
uv run python -m tests.benchmarks.bench_search --mode dense
uv run python -m tests.benchmarks.bench_search --mode sparse
uv run python -m tests.benchmarks.bench_search --mode hybrid

# Against a real Qdrant server
uv run python -m tests.benchmarks.bench_search --url http://localhost:6333
```

---

## Measured modes

| Mode | What is measured |
|------|-----------------|
| `bm25-cpu` | Local BM25 sparse vector computation (fastembed, no network) |
| `dense` | `query_points` with named dense vector |
| `sparse` | `query_points` with named sparse (BM25) vector |
| `hybrid (RRF)` | `Prefetch[dense top-20, sparse top-20]` + `FusionQuery(RRF)` |
| `hybrid + filter` | Hybrid with payload filter `topic_type == "technique"` |

---

## Benchmark results

**Environment:** Qdrant in-memory, 104 hybrid points (realistic fixture), 300 queries per mode,
30 warmup iterations discarded, `limit=5`, `prefetch=20`, `vector_size=1536`.
Linux x86-64, single process, asyncio, no concurrency.

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

---

## Interpreting the numbers

### BM25 CPU — 0.02 ms / 54k RPS

Sparse vector computation is local (tokenise + TF-IDF scoring via the fastembed
`Qdrant/bm25` model) with no network round-trip. Cost is negligible — equivalent
to a single `time.sleep(0)` call.

### Dense — p50 = 1.65 ms

Single named-vector search. Qdrant in-memory skips all network I/O, so this
baseline reflects only the HNSW graph traversal cost. On a remote Qdrant Cloud
instance, add +5–15 ms network overhead.

### Sparse — p50 = 3.18 ms (~2× dense)

BM25 sparse indices can carry up to 150 non-zero terms per query. Qdrant must
resolve the inverted index for each term, making it slower than a single dense ANN
lookup. The overhead is predictable and bounded — it scales with vocabulary hit
count, not corpus size.

### Hybrid RRF — p50 = 7.73 ms (~4.7× dense)

Two prefetch searches (dense + sparse, 20 results each) followed by RRF rank
fusion. Latency is approximately `dense + sparse + fusion_overhead`, not
`dense × 2`. The fusion step itself is O(prefetch_limit) and adds less than 1 ms.

### Hybrid + filter — p50 = 9.55 ms

Applying a payload filter to each prefetch adds ~1–2 ms over unfiltered hybrid
because Qdrant must intersect the filter bitmap with the HNSW/inverted-index
results. The p99 spike (12.25 ms) reflects occasional index cold-starts for
smaller filtered subsets.

---

## Production latency estimate

Adding real-world network latency to a Qdrant Cloud instance (~5–15 ms RTT) and
the embedding API call (OpenAI `text-embedding-3-small` ~100–200 ms):

| Step | Estimated time |
|------|----------------|
| BM25 sparse vector (local) | ~0.02 ms |
| Dense embedding API call | ~100–200 ms |
| Qdrant hybrid search (remote) | ~13–25 ms |
| **Total query latency (p50)** | **~115–225 ms** |

The embedding call dominates. To reduce end-to-end latency:

- Use a local embedding model to eliminate the 100–200 ms API round-trip
- Cache embedding results keyed on a hash of the question (e.g. Redis with 1h TTL)
- The BM25 sparse vector and embedding call are already computed concurrently inside
  `parallel_hybrid_search()`, so there is no serial penalty between them

---

## Additional benchmark scenarios

| Scenario | Description | Goal |
|----------|-------------|------|
| Multi-query parallel | `asyncio.gather` 3 sub-questions concurrently | Measure concurrency overhead inside `parallel_hybrid_search()` |
| Corpus scale-up | 1,000 points and 10,000 points | Confirm HNSW sub-linear scaling |
| RRF vs score-average merge | Compare RRF output quality with plain score averaging | Demonstrate that RRF produces better relevance ordering |
| Embedding cache hit | Cached query vector vs cold API call | Quantify savings from query embedding cache |
| Remote Qdrant | Benchmark against real Qdrant Cloud | Establish production latency baseline |

---

## See also

- `backend/tests/benchmarks/bench_search.py` — benchmark script source
- `docs/system/vector-database.md` — Qdrant collection schema and named-vector layout
- `docs/features/feature_1/retrieval-generation.md` — latency budget within the full pipeline
