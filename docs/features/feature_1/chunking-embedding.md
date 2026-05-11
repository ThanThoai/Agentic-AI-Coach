# Chunking & Embedding

**Component of:** Feature 1 — Fitness Knowledge RAG
**Last updated:** 2026-05-11

---

## Responsibility

This component owns the **offline ingestion pipeline**: reading raw markdown files,
splitting them into semantically meaningful chunks, generating vector embeddings,
and storing everything in Qdrant. It runs once at project setup and is re-run
whenever the knowledge base changes.

```
knowledge-base/*.md
      │
      ▼  parser.py
  ParsedChunk[]          ← one chunk per H2 section
      │
      ▼  chunker.py
  Chunk[]                ← oversized sections split further
      │
      ▼  embedder.py
  (text, vector)[]       ← 1536-dimensional float vectors
      │
      ▼  ingestion.py
  Qdrant upsert          ← idempotent, deterministic IDs
```

---

## 1. Document parsing

**File:** `backend/app/rag/parser.py`

### Knowledge-base structure

All 20 markdown documents follow the same pattern:

```markdown
# Document Title              ← H1: one per file, becomes doc_title

## Section Name               ← H2: chunk boundary
Body text, bullet lists, tables, code blocks...

### Optional Subsection       ← H3: stays inside the parent H2 chunk
More detail...

## Next Section               ← H2: next chunk boundary
...
```

### Parsing algorithm

Split by H2 (`##`) headers. Each H2 block — title plus all body text until the next
H2 — becomes one `ParsedChunk`. H3 subsections are **not** split further; they remain
inside the parent chunk to preserve context.

```python
@dataclass
class ParsedChunk:
    text: str            # full section text: "## Section Title\nbody..."
    doc_title: str       # H1 title extracted from the file
    section_title: str   # H2 title, e.g. "Methods of Progressive Overload"
    source_file: str     # filename, e.g. "08-progressive-overload.md"
    chunk_index: int     # 0-based within the document
```

**Edge cases:**

| Case | Handling |
|------|----------|
| Content before first H2 | Treated as synthetic section with `section_title = "Overview"` |
| H3 subsections | Kept inside parent H2 chunk |
| Code blocks / tables | Preserved verbatim inside the chunk text |
| Empty H2 section | Skipped (not stored) |
| File with no H2 | Entire file body becomes one chunk with `section_title = doc_title` |

### Expected output

20 docs × ~4–6 sections average = **~80–120 total chunks**.

```
08-progressive-overload.md  →  5 chunks
  [0] Overview (content before first H2 — if any)
  [1] Definition
  [2] Methods of Progressive Overload
  [3] Double Progression Method
  [4] Rate of Progression
  [5] Key Principle
```

---

## 2. Chunking (size guard)

**File:** `backend/app/rag/chunker.py`

### Why a size guard is needed

Most H2 sections in these docs fit within 512 tokens. However, some are longer:
- `14-workout-split-ppl.md` — the exercise list section can exceed 600 tokens
- `18-common-injuries.md` — multiple injury descriptions in one section

Sending an oversized chunk to the embedding API wastes tokens and may degrade
retrieval quality (vectors of very long texts become less discriminative).

### Algorithm

```
for each ParsedChunk:
    token_count = tiktoken.count(chunk.text)

    if token_count ≤ MAX_TOKENS:
        yield chunk as-is

    else:
        split into sub-chunks with sliding window:
            window  = MAX_TOKENS   tokens
            overlap = OVERLAP_TOKENS tokens
        each sub-chunk inherits all metadata from the parent
        chunk_index becomes  f"{parent_index}.{sub_index}"
```

**Parameters:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `MAX_TOKENS` | 512 | Within optimal range for `text-embedding-3-small` |
| `OVERLAP_TOKENS` | 64 | Prevents context loss at split boundaries |
| Tokeniser | `tiktoken` `cl100k_base` | Same tokeniser used by OpenAI embedding model |

### Why these values

- **512 tokens** aligns with the training regime of most embedding models and avoids
  the performance degradation that occurs with very long sequences.
- **64-token overlap** (~1–2 sentences) ensures that a sentence cut at a boundary
  still appears in one of the two adjacent chunks.
- Using `tiktoken` (not a word count) gives an exact token count matching what the
  API will bill and process.

---

## 3. Embedding

**File:** `backend/app/rag/embedder.py`

### Model

| Setting | Value |
|---------|-------|
| Provider | `DEFAULT_EMBEDDING_PROVIDER` (env, default: `openai`) |
| Model | `OPENAI_EMBEDDING_MODEL` (env, default: `text-embedding-3-small`) |
| Output dimensions | 1536 |
| Max batch size | 50 chunks per API call |

The embedder calls `BaseLLMProvider.embed()`, which is implemented for every provider.
Switching to Gemini `text-embedding-004` (768 dims) requires only one env var change —
**but the Qdrant collection must be deleted and recreated** because dimensions are
fixed at collection creation time.

### Batching

```
chunks = [c0, c1, ..., c103]   # 104 chunks
batches = split(chunks, size=50)

for batch in batches:
    texts  = [c.text for c in batch]
    vectors = await provider.embed(texts)
    # vectors[i] corresponds to batch[i]
```

Batching to 50 (well below the API limit) gives fine-grained retry granularity:
if one batch fails, only 50 chunks need to be re-embedded, not the whole corpus.

### Cost estimate (one-time ingestion)

```
~104 chunks × ~200 tokens avg = ~20,800 tokens
text-embedding-3-small:  $0.00002 / 1k tokens
Total: ~$0.0004  (less than $0.001)
```

---

## 4. Qdrant ingestion

**File:** `backend/app/rag/ingestion.py`

### Collection setup

```python
await qdrant.ensure_collection(vector_size=1536, distance=Distance.COSINE)
```

`ensure_collection` is idempotent — it creates the collection only if it does not
already exist. This makes the ingestion script safe to re-run.

### Payload schema

Each point stored in Qdrant carries this payload alongside its vector:

```json
{
  "source_file":    "08-progressive-overload.md",
  "doc_title":      "Progressive Overload",
  "section_title":  "Methods of Progressive Overload",
  "chunk_index":    "2",
  "text":           "## Methods of Progressive Overload\n\n### 1. Increase Weight\n..."
}
```

`text` is stored so the retriever can return it in the response without a second lookup.

### Idempotency via deterministic IDs

Each chunk is assigned a **deterministic UUID** derived from its identity:

```python
import hashlib, uuid

def chunk_id(source_file: str, chunk_index: str) -> str:
    key = f"{source_file}::{chunk_index}"
    return str(uuid.UUID(hashlib.sha256(key.encode()).hexdigest()[:32]))
```

Re-running `ingest` with the same documents performs an **upsert**, not a duplicate
insert. Chunks that no longer exist (e.g. a section was deleted) are **not** removed
automatically — a full re-ingest (`--force-recreate` flag) is required for that case.

### CLI

```bash
# Standard ingest (idempotent upsert)
uv run python -m app.rag.ingest

# Force delete + recreate collection (use after structural doc changes)
uv run python -m app.rag.ingest --force-recreate

# Ingest a single file (useful during development)
uv run python -m app.rag.ingest --file knowledge-base/08-progressive-overload.md
```

### Expected log output

```
[INFO] rag.ingest  docs_found=20 chunks_parsed=104
[INFO] rag.ingest  embedding_batches=3 tokens_used=20840
[INFO] rag.ingest  upserted=104 skipped=0 collection=knowledge_base duration_ms=4210
```

---

## 5. Data flow diagram

```
 knowledge-base/
 ├── 01-bench-press.md
 ├── 08-progressive-overload.md   ← example
 └── ...

          │  parse_document()
          ▼
 ParsedChunk(
   text          = "## Methods of Progressive Overload\n...",
   doc_title     = "Progressive Overload",
   section_title = "Methods of Progressive Overload",
   source_file   = "08-progressive-overload.md",
   chunk_index   = "2"
 )
          │  split_if_oversized()
          ▼
 Chunk (same fields, possibly sub-indexed as "2.0", "2.1")

          │  embed(chunk.text)
          ▼
 vector = [0.021, -0.043, ..., 0.017]   # 1536 floats

          │  qdrant.upsert(id, vector, payload)
          ▼
 Qdrant point:
   id      = "a3f2...uuid...7d01"
   vector  = [...]
   payload = { source_file, doc_title, section_title, chunk_index, text }
```
