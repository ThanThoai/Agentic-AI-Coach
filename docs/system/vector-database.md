# Vector Database (Qdrant)

**Version:** 0.1.0 | **Last updated:** 2026-05-11

## Overview

Qdrant is used for semantic search across:
1. **Knowledge base** — 20 fitness documents (form guides, periodization, nutrition, etc.)
2. **Workout history** — User workout notes embedded for similarity search

## Collections

| Collection | Env var | Vector size | Distance | Content |
|---|---|---|---|---|
| `knowledge_base` | `QDRANT_COLLECTION_KNOWLEDGE` | 1536 | Cosine | Chunked fitness docs |
| `workout_embeddings` | `QDRANT_COLLECTION_WORKOUTS` | 1536 | Cosine | User workout notes |

Vector size matches `text-embedding-3-small` (OpenAI). Change both together if you switch embedding models.

## Client

`QdrantVectorDB` in `app/vectordb/qdrant.py` wraps `AsyncQdrantClient`:

```python
db = QdrantVectorDB.from_url(
    url=settings.qdrant_url,
    collection_name=settings.qdrant_collection_knowledge,
    api_key=settings.qdrant_api_key,
)

# Ensure collection exists (idempotent)
await db.ensure_collection(vector_size=1536)

# Upsert
ids = await db.upsert(vectors=embeddings, payloads=payloads)

# Search
results = await db.search(query_vector=query_embedding, limit=5)

# Filter by payload field
results = await db.search(
    query_vector=query_embedding,
    limit=5,
    filter_by={"topic": "progressive_overload"},
)
```

## Local Development

Run Qdrant locally via Docker:

```bash
docker run -p 6333:6333 qdrant/qdrant
```

Or use `:memory:` mode for tests — no server needed:

```python
QdrantVectorDB.from_url(":memory:", "test_collection")
```

## Payload Schema

### knowledge_base

```json
{
  "source_file": "08-progressive-overload.md",
  "chunk_index": 0,
  "topic": "progressive_overload",
  "text": "Progressive overload is the principle of..."
}
```

### workout_embeddings

```json
{
  "user_id": "uuid",
  "workout_id": "uuid",
  "date": "2026-01-15",
  "exercise": "squat",
  "notes": "Felt strong, depth was good"
}
```

## Indexing Strategy

Knowledge base docs are re-indexed on demand via:

```bash
uv run python -m app.scripts.ingest_knowledge_base
```

Workout notes are indexed incrementally at write time (service layer triggers embedding + upsert after workout creation).
