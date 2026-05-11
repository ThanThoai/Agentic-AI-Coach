# Chunking & Embedding

**Component of:** Feature 1 — Fitness Knowledge RAG
**Last updated:** 2026-05-11

---

## Responsibility

This component owns the **offline ingestion pipeline**: reading raw markdown files,
splitting them into semantically meaningful chunks, enriching each chunk with structured
metadata, generating vector embeddings (with contextual prefixes), and storing everything
in Qdrant.

```
knowledge-base/*.md
      │
      ▼  parser.py
  ParsedChunk[]              ← one chunk per H2 section
      │
      ▼  metadata.py          ← NEW
  ParsedChunk + metadata     ← tags, difficulty, topic_type extracted
      │
      ▼  chunker.py
  Chunk[]                    ← oversized sections split further
      │
      ▼  embedder.py          ← NEW: contextual prefix applied here
  (embed_text, vector)[]     ← 1536-dimensional float vectors
      │
      ▼  ingestion.py
  Qdrant upsert              ← idempotent, deterministic IDs, rich payload
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
    # Populated by metadata.py (Step 2):
    tags: list[str]      = field(default_factory=list)
    difficulty: list[str]= field(default_factory=list)
    topic_type: str      = ""
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

## 2. Metadata extraction

**File:** `backend/app/rag/metadata.py`

Structured metadata is attached to each `ParsedChunk` after parsing. It enables
**filtered retrieval** in Qdrant — e.g. "only search technique docs" or "only return
beginner-appropriate content" — without reranking the entire corpus.

### Metadata schema

```python
@dataclass
class ChunkMetadata:
    tags:       list[str]   # exercise muscles, movements, concepts
    difficulty: list[str]   # subset of ["beginner", "intermediate", "advanced"]
    topic_type: str         # "technique" | "programming" | "safety" | "nutrition"
```

### Field definitions

**`topic_type`** — the primary category of the document:

| Value | Description | Example docs |
|-------|-------------|--------------|
| `technique` | Exercise form, execution, cues | bench-press, squat, deadlift, pull-up |
| `programming` | Training structure, progression, periodization | progressive-overload, periodization, deload, PPL split, one-rep-max |
| `safety` | Injury prevention, warm-up, recovery | common-injuries, warm-up-cooldown, muscle-recovery |
| `nutrition` | Food, macros, fuelling | nutrition-basics |

**`difficulty`** — which training levels the content is relevant to.
A doc can apply to multiple levels:

| Value | Meaning |
|-------|---------|
| `beginner` | < 1 year of consistent training |
| `intermediate` | 1–3 years, stalled on linear progression |
| `advanced` | 3+ years, needs periodization |

**`tags`** — fine-grained labels for filtering and future faceted search:

```python
# Movement pattern
"compound", "isolation", "push", "pull", "hinge", "squat_pattern", "carry"

# Muscle groups
"chest", "back", "shoulders", "legs", "arms", "core",
"upper_body", "lower_body", "full_body"

# Concepts
"strength", "hypertrophy", "endurance", "powerlifting", "bodybuilding",
"progressive_overload", "periodization", "deload", "rpe", "rir",
"warm_up", "recovery", "injury_prevention", "nutrition", "ppl_split"
```

### Extraction strategy

Metadata is extracted with a **hybrid approach**: rule-based first (fast, zero cost),
LLM-assisted as a fallback for ambiguous cases.

#### Strategy A — Rule-based (applied to all docs)

Rules are keyed on `source_file` name and H1 title keywords:

```python
TOPIC_TYPE_RULES: dict[str, str] = {
    "bench-press":         "technique",
    "squat":               "technique",
    "deadlift":            "technique",
    "overhead-press":      "technique",
    "barbell-row":         "technique",
    "pull-up":             "technique",
    "isolation":           "technique",
    "progressive-overload":"programming",
    "periodization":       "programming",
    "deload":              "programming",
    "rpe-rir":             "programming",
    "one-rep-max":         "programming",
    "workout-split":       "programming",
    "training-for-beginners": "programming",
    "muscle-recovery":     "safety",
    "common-injuries":     "safety",
    "warm-up-cooldown":    "safety",
    "nutrition":           "nutrition",
}

TAG_RULES: dict[str, list[str]] = {
    "bench-press":     ["compound", "push", "upper_body", "chest", "powerlifting"],
    "squat":           ["compound", "squat_pattern", "lower_body", "legs", "powerlifting"],
    "deadlift":        ["compound", "hinge", "full_body", "back", "legs", "powerlifting"],
    "overhead-press":  ["compound", "push", "upper_body", "shoulders"],
    "barbell-row":     ["compound", "pull", "upper_body", "back"],
    "pull-up":         ["compound", "pull", "upper_body", "back", "arms"],
    "isolation":       ["isolation", "hypertrophy"],
    "progressive-overload": ["progressive_overload", "strength", "hypertrophy"],
    "periodization":   ["periodization", "programming", "strength"],
    "deload":          ["deload", "recovery", "programming"],
    "rpe-rir":         ["rpe", "rir", "strength", "programming"],
    "one-rep-max":     ["strength", "powerlifting", "programming"],
    "workout-split-ppl":     ["ppl_split", "programming", "hypertrophy"],
    "workout-split-upper-lower": ["programming", "strength", "hypertrophy"],
    "workout-split-full-body":   ["programming", "full_body", "beginner"],
    "muscle-recovery": ["recovery", "injury_prevention"],
    "common-injuries": ["injury_prevention", "safety"],
    "warm-up-cooldown":["warm_up", "recovery", "safety"],
    "nutrition-basics":["nutrition"],
    "training-for-beginners": ["beginner", "programming", "strength"],
}

DIFFICULTY_RULES: dict[str, list[str]] = {
    "training-for-beginners":       ["beginner"],
    "workout-split-full-body":      ["beginner", "intermediate"],
    "workout-split-ppl":            ["intermediate", "advanced"],
    "workout-split-upper-lower":    ["intermediate", "advanced"],
    "periodization":                ["intermediate", "advanced"],
    "one-rep-max":                  ["intermediate", "advanced"],
    # All others default to all three levels
}
DEFAULT_DIFFICULTY = ["beginner", "intermediate", "advanced"]
```

#### Strategy B — LLM-assisted (fallback for new/unlisted docs)

If a document's filename does not match any rule key, use a cheap LLM call to extract
metadata during ingestion:

```python
METADATA_EXTRACTION_PROMPT = """
Analyse this fitness document and return JSON only:
{
  "topic_type": "technique" | "programming" | "safety" | "nutrition",
  "difficulty": list of applicable levels from ["beginner","intermediate","advanced"],
  "tags": list of 3-6 concise lowercase tags (muscle groups, movements, concepts)
}

Document title: {doc_title}
Content excerpt (first 300 chars): {excerpt}
"""
```

This LLM call is made **once per document** at ingest time, not at query time.
Cost: ~200 tokens × $0.00025/1k (Haiku) = ~$0.00005 per doc.

### Full metadata example per document

```python
# 01-bench-press.md
ChunkMetadata(
    tags       = ["compound", "push", "upper_body", "chest", "powerlifting"],
    difficulty = ["beginner", "intermediate", "advanced"],
    topic_type = "technique",
)

# 08-progressive-overload.md
ChunkMetadata(
    tags       = ["progressive_overload", "strength", "hypertrophy"],
    difficulty = ["beginner", "intermediate", "advanced"],
    topic_type = "programming",
)

# 13-nutrition-basics.md
ChunkMetadata(
    tags       = ["nutrition"],
    difficulty = ["beginner", "intermediate", "advanced"],
    topic_type = "nutrition",
)

# 18-common-injuries.md
ChunkMetadata(
    tags       = ["injury_prevention", "safety"],
    difficulty = ["beginner", "intermediate", "advanced"],
    topic_type = "safety",
)
```

### Using metadata for filtered retrieval

At query time, the caller can optionally narrow the search:

```python
# Only search technique documents
results = await qdrant.search(
    query_vector   = question_embedding,
    limit          = 5,
    score_threshold= 0.35,
    filter_by      = {"topic_type": "technique"},
)

# Only search content relevant to beginners
results = await qdrant.search(
    query_vector   = question_embedding,
    limit          = 5,
    filter_by      = {"difficulty": "beginner"},   # Qdrant array-contains match
)
```

---

## 3. Chunking (size guard)

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

---

## 4. Contextual prefix (breadcrumb embedding)

**File:** `backend/app/rag/embedder.py`

### Problem: context loss in isolated chunks

When a chunk is embedded in isolation, the vector captures only the section content —
not *where* that section sits. For example, the chunk text:

```
## Rate of Progression
- Beginners: Can add weight almost every session...
- Intermediate: Weekly or biweekly progression...
```

…is ambiguous without knowing it belongs to "Progressive Overload". A question like
*"how fast should I progress on squat?"* might not strongly match this chunk because
the word "squat" does not appear in the section text.

### Solution: prepend a contextual prefix before embedding

Before calling the embedding API, a **breadcrumb prefix** is prepended to the chunk
text. This prefix is used **only for the embedding call** — it is not stored in the
Qdrant `text` payload (which stays clean for the LLM prompt).

```
embed_text  ≠  stored_text

embed_text  = prefix + "\n\n" + chunk.text
stored_text = chunk.text   (unchanged)
```

### Prefix format

```
Document: {doc_title} | Section: {section_title} | Type: {topic_type} | Tags: {tags_csv}

{chunk.text}
```

**Concrete example** for the progressive overload chunk above:

```
Document: Progressive Overload | Section: Rate of Progression | Type: programming | Tags: progressive_overload, strength, hypertrophy

## Rate of Progression
- **Beginners**: Can add weight almost every session (newbie gains)
- **Intermediate**: Weekly or biweekly progression
- **Advanced**: Monthly or per training block (mesocycle)
```

### Why this works

The embedding vector now encodes:
- The section content (original signal)
- The parent document context (`Progressive Overload`)
- The structural position (`Rate of Progression`)
- The semantic category (`programming`, `progressive_overload`)

A question like *"how fast should a beginner add weight?"* now matches via both
the content similarity **and** the shared `beginner` + `progressive_overload` vocabulary
in the prefix — without requiring those exact words to appear in the section body.

### Implementation

```python
def build_embed_text(chunk: ParsedChunk) -> str:
    tags_csv = ", ".join(chunk.tags)
    prefix = (
        f"Document: {chunk.doc_title} | "
        f"Section: {chunk.section_title} | "
        f"Type: {chunk.topic_type} | "
        f"Tags: {tags_csv}"
    )
    return f"{prefix}\n\n{chunk.text}"


async def embed_chunks(
    chunks: list[ParsedChunk],
    provider: BaseLLMProvider,
    batch_size: int = 50,
) -> list[tuple[ParsedChunk, list[float]]]:
    results: list[tuple[ParsedChunk, list[float]]] = []
    for batch in batched(chunks, batch_size):
        embed_texts = [build_embed_text(c) for c in batch]  # prefix applied here
        vectors = await provider.embed(embed_texts)
        results.extend(zip(batch, vectors))
    return results
```

### Token budget impact

The prefix adds ~25–35 tokens per chunk. With 104 chunks:

```
Without prefix:  ~104 × 200 tokens = 20,800 tokens  (~$0.0004)
With prefix:     ~104 × 230 tokens = 23,920 tokens  (~$0.0005)

Delta: +3,120 tokens ≈ +$0.0001  — negligible cost, significant retrieval gain
```

---

## 5. Embedding model

**File:** `backend/app/rag/embedder.py`

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

---

## 6. Qdrant ingestion

**File:** `backend/app/rag/ingestion.py`

### Collection setup

```python
await qdrant.ensure_collection(vector_size=1536, distance=Distance.COSINE)
```

### Payload schema (updated with metadata)

Each Qdrant point now carries the full metadata alongside the chunk content:

```json
{
  "source_file":    "08-progressive-overload.md",
  "doc_title":      "Progressive Overload",
  "section_title":  "Methods of Progressive Overload",
  "chunk_index":    "2",
  "text":           "## Methods of Progressive Overload\n\n### 1. Increase Weight\n...",

  "topic_type":     "programming",
  "difficulty":     ["beginner", "intermediate", "advanced"],
  "tags":           ["progressive_overload", "strength", "hypertrophy"]
}
```

> `text` stores the **original chunk text without the prefix** — the LLM receives clean
> content when the chunk is used as context during generation.

### Idempotency via deterministic IDs

```python
import hashlib, uuid

def chunk_id(source_file: str, chunk_index: str) -> str:
    key = f"{source_file}::{chunk_index}"
    return str(uuid.UUID(hashlib.sha256(key.encode()).hexdigest()[:32]))
```

### CLI

```bash
# Standard ingest (idempotent upsert)
uv run python -m app.rag.ingest

# Force delete + recreate collection (use after structural doc changes or embedding model change)
uv run python -m app.rag.ingest --force-recreate

# Ingest a single file (useful during development)
uv run python -m app.rag.ingest --file knowledge-base/08-progressive-overload.md
```

### Expected log output

```
[INFO] rag.ingest  docs_found=20 chunks_parsed=104
[INFO] rag.ingest  metadata_extracted=20 strategy=rule_based llm_fallback=0
[INFO] rag.ingest  embedding_batches=3 tokens_used=23920
[INFO] rag.ingest  upserted=104 skipped=0 collection=knowledge_base duration_ms=4380
```

---

## 7. Full data flow diagram

```
 knowledge-base/08-progressive-overload.md
          │
          ▼  parse_document()
 ParsedChunk(
   text          = "## Methods of Progressive Overload\n...",
   doc_title     = "Progressive Overload",
   section_title = "Methods of Progressive Overload",
   source_file   = "08-progressive-overload.md",
   chunk_index   = "2",
   tags=[], difficulty=[], topic_type=""    ← not yet filled
 )
          │
          ▼  extract_metadata()
 ParsedChunk(
   ...same fields...,
   tags          = ["progressive_overload", "strength", "hypertrophy"],
   difficulty    = ["beginner", "intermediate", "advanced"],
   topic_type    = "programming"
 )
          │
          ▼  split_if_oversized()
 Chunk (same fields, chunk_index may become "2.0", "2.1" if split)

          │
          ▼  build_embed_text()        ← contextual prefix applied
 embed_text =
   "Document: Progressive Overload | Section: Methods of Progressive Overload |
    Type: programming | Tags: progressive_overload, strength, hypertrophy

    ## Methods of Progressive Overload
    ..."

          │
          ▼  provider.embed([embed_text])
 vector = [0.021, -0.043, ..., 0.017]   # 1536 floats

          │
          ▼  qdrant.upsert(id, vector, payload)
 Qdrant point:
   id      = "a3f2...uuid...7d01"       ← deterministic from sha256
   vector  = [...]                      ← embedded WITH prefix
   payload = {
     source_file, doc_title, section_title, chunk_index,
     text,           ← stored WITHOUT prefix (clean for LLM)
     topic_type,     ← "programming"
     difficulty,     ← ["beginner", "intermediate", "advanced"]
     tags            ← ["progressive_overload", "strength", "hypertrophy"]
   }
```
