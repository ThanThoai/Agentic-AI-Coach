# Testing Guide

> **Content has been moved to `docs/system/testing/`.**
> This file is kept to avoid breaking existing links.

---

## Quick start

```bash
# Mock tests (CI-safe, no API keys required)
uv run pytest tests/mock/

# Live tests (requires real API keys)
uv run pytest -m live

# Benchmarks
uv run python -m tests.benchmarks.bench_search
```

---

## Index

| Document | Content |
|----------|---------|
| [testing/README.md](testing/README.md) | Overview, test tiers, coverage summary, test infrastructure |
| [testing/feature-1-guardrails.md](testing/feature-1-guardrails.md) | 3-layer guardrail pipeline — 49 scenarios |
| [testing/feature-1-ingestion.md](testing/feature-1-ingestion.md) | RAG ingestion — Parser, Chunker, Embedder, HybridCollection |
| [testing/feature-1-query-retrieval.md](testing/feature-1-query-retrieval.md) | Query processing, retriever, RAG endpoint (including pending tests) |
| [testing/llm-providers.md](testing/llm-providers.md) | LLM provider mock + live tests, provider capability matrix |
| [testing/benchmarks.md](testing/benchmarks.md) | Qdrant search latency benchmark, results, and interpretation |
