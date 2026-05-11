# Testing Overview

**Last updated:** 2026-05-11

---

## Test tiers

| Tier | Location | When to run | External deps |
|------|----------|-------------|---------------|
| **Mock** | `backend/tests/mock/` | Every commit, CI | None — all I/O intercepted |
| **Live** | `backend/tests/live/` | Pre-release, on demand | Real API keys + network |
| **Benchmark** | `backend/tests/benchmarks/` | On-demand, performance gates | Qdrant in-memory or remote |

```bash
# Mock only (default, CI-safe)
uv run pytest tests/mock/

# Live (requires real .env keys)
uv run pytest -m live

# Benchmarks
uv run python -m tests.benchmarks.bench_search
```

The root `tests/conftest.py` loads `.env.test` (or falls back to `.env`) before any import,
so `Settings()` initialises cleanly without exporting env vars in the shell.

---

## Documents in this folder

| Document | Scope |
|----------|-------|
| [feature-1-guardrails.md](feature-1-guardrails.md) | 3-layer guardrail pipeline — Layer 1 rule filter, Layer 2 intent classifier, Layer 3 output filter |
| [feature-1-ingestion.md](feature-1-ingestion.md) | RAG ingestion pipeline — Parser, Metadata, Chunker, Embedder, ChunkId, Hybrid collection |
| [feature-1-query-retrieval.md](feature-1-query-retrieval.md) | Query processing + retrieval — QueryProcessor, VectorDB, Retriever, RAG endpoint |
| [llm-providers.md](llm-providers.md) | LLM provider adapters — mock HTTP interception + live smoke tests |
| [benchmarks.md](benchmarks.md) | Qdrant search latency benchmark — all modes, results, interpretation |

---

## Coverage summary

| Module | Mock tests | Live tests | Status |
|--------|-----------|-----------|--------|
| `app/rag/guardrails.py` | 49 cases | — | ✅ Complete |
| `app/rag/parser.py` | 9 cases | — | ✅ Complete |
| `app/rag/metadata.py` | 5 cases | — | ✅ Complete |
| `app/rag/chunker.py` | 9 cases | — | ✅ Complete |
| `app/rag/embedder.py` | 6 cases | — | ✅ Complete |
| `app/rag/ingestion.py` | 4 cases | — | ✅ Complete |
| `app/vectordb/qdrant.py` | 8 cases | 1 case | ✅ Complete |
| `app/llm/*` | 6 cases | 8 cases | ✅ Complete |
| `app/rag/query_processor.py` | — | — | 🔲 Pending |
| `app/rag/retriever.py` | — | — | 🔲 Pending |
| `app/api/v1/rag.py` | — | — | 🔲 Pending |

---

## Test infrastructure

### `MockLLMProvider` (`tests/mock/conftest.py`)

Drop-in replacement for any `BaseLLMProvider`. Returns a fixed `LLMResponse` and embedding
vectors — no HTTP calls made.

```python
class MockLLMProvider:
    async def complete(...) -> LLMResponse        # returns MOCK_RESPONSE
    async def stream(...)  -> AsyncIterator[str]  # yields tokens from MOCK_RESPONSE
    async def embed(...)   -> list[list[float]]   # returns [0.1, 0.2, 0.3, 0.4, 0.5]
```

### `ControlledMockLLMProvider` (`tests/mock/test_guardrails.py`)

Parameterised variant — `content` is set per-test to simulate different LLM responses:

```python
provider = ControlledMockLLMProvider('{"intent": "MEDICAL_REFUSE", "reason": "post-surgical"}')
result = await classify_intent(question, provider)
```

### Qdrant in-memory fixture (`tests/mock/conftest.py`)

```python
@pytest.fixture
async def vector_db():
    db = QdrantVectorDB.from_url(":memory:", "test_collection")
    await db.ensure_collection(vector_size=5)
    return db
```

No real Qdrant server required. Each test function receives a fresh, empty collection.

---

## Adding new tests

- Mock tests → `tests/mock/`. Use `MockLLMProvider`; use the Qdrant fixture for vector operations.
- Live tests → `tests/live/`. Mark with `@pytest.mark.live`; add a skip guard if the API key may be absent.
- New fixtures → `tests/mock/conftest.py` (shared) or the specific test file (local).
- Never call `Settings()` directly in test files — the root conftest initialises it from `.env.test`.
- Document new test scenarios in the relevant file in this folder.

---

## See also

- `docs/features/feature_1/guardrails.md` — guardrail design spec
- `docs/features/feature_1/chunking-embedding.md` — ingestion pipeline spec
- `docs/features/feature_1/retrieval-generation.md` — retrieval & generation spec
- `docs/system/vector-database.md` — Qdrant collection schema
