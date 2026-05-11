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

### Token thresholds

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `MIN_TOKENS` | 50 | Below this a chunk embeds poorly — too little signal |
| `MAX_TOKENS` | 512 | Upper limit for `text-embedding-3-small` optimal range |
| `OVERLAP_TOKENS` | 64 | Prevents context loss at split boundaries (~1–2 sentences) |
| Tokeniser | `tiktoken` `cl100k_base` | Exact token count matching the embedding model |

### Algorithm

```
for each ParsedChunk:
    token_count = tiktoken.count(chunk.text)

    if token_count < MIN_TOKENS:
        → too-short path  (see below)

    elif token_count ≤ MAX_TOKENS:
        yield chunk as-is

    else:
        → too-long path  (see below)
```

---

### Edge case A — Section too short (< 50 tokens)

**Problem:** A section with only a heading and 1–2 lines produces a vector with very
little signal. It will match broadly and weakly, polluting search results.

Known examples in this corpus:
- `## Key Principle` in `08-progressive-overload.md` — single paragraph, ~40 tokens
- `## Overview` synthetic sections (content before first H2) — often only 2–3 lines

**Strategy: merge with the next sibling section**

```
if token_count < MIN_TOKENS:
    buffer this chunk
    on next iteration, prepend the buffered text to the current chunk
    yield the merged chunk

# Edge case within the edge case:
# If the short chunk is the LAST section in a document,
# merge it with the PREVIOUS chunk instead.
```

Merged chunk metadata: keep `section_title` of the **first** (shorter) section,
append `" + {next_section_title}"` to make the boundary visible in the payload.

```python
# Example merge result
ParsedChunk(
    section_title = "Key Principle + (end of document)",
    text          = "## Key Principle\n...\n\n## (merged content)",
    chunk_index   = "4+5",   # signals a merge happened
)
```

**Why not just skip short sections?**
Skipping silently loses content. A short "Key Principle" section may be the most
important summary sentence in the document — exactly what a user asking a high-level
question needs.

**Why 50 tokens as the floor?**
50 tokens ≈ 2–3 sentences — the minimum amount of text for `text-embedding-3-small`
to produce a useful directional vector. Empirically, vectors for texts shorter than
this have cosine similarities of 0.4–0.6 with semantically unrelated content (noise).

---

### Edge case B — Section too long (> 512 tokens)

**Problem:** Oversized chunks degrade embedding quality. Vectors of very long texts
become less discriminative — they average over too many concepts and match too broadly.

Known examples in this corpus:
- `14-workout-split-ppl.md` — exercise list section can reach ~650 tokens
- `18-common-injuries.md` — multiple injury blocks in one section can reach ~700 tokens

**Strategy: sliding-window split**

```python
def split_oversized(chunk: ParsedChunk) -> list[ParsedChunk]:
    tokens = tokenize(chunk.text)           # list of token ids
    sub_chunks = []
    start = 0
    sub_index = 0

    while start < len(tokens):
        end = min(start + MAX_TOKENS, len(tokens))
        window_text = detokenize(tokens[start:end])
        sub_chunks.append(ParsedChunk(
            text          = window_text,
            chunk_index   = f"{chunk.chunk_index}.{sub_index}",
            # all other fields inherited from parent:
            doc_title     = chunk.doc_title,
            section_title = chunk.section_title,
            source_file   = chunk.source_file,
            tags          = chunk.tags,
            difficulty    = chunk.difficulty,
            topic_type    = chunk.topic_type,
        ))
        if end == len(tokens):
            break
        start = end - OVERLAP_TOKENS        # step back for overlap
        sub_index += 1

    return sub_chunks
```

**Overlap behaviour:**
The last `OVERLAP_TOKENS` (64) tokens of each window are repeated at the start of
the next — ensuring a sentence cut at a boundary still fully appears in one of the
two adjacent sub-chunks.

**Multi-split (very long sections > 1024 tokens):**
The `while` loop handles arbitrarily long sections — it keeps sliding until `end`
reaches the final token, so a 900-token section produces two sub-chunks
(`0.0` and `0.1`), a 1400-token section produces three (`0.0`, `0.1`, `0.2`), etc.

---

### Edge case C — Section that is almost entirely code or a table

**Problem:** A section whose body is 90%+ a fenced code block or markdown table
will produce a vector dominated by syntax tokens (`|`, `-`, `` ` ``, `{`, `}`).
These vectors match poorly against natural-language queries.

In this corpus the risk is low (fitness docs rarely have code), but some sections
include structured data like exercise tables.

**Strategy: detect and annotate, do not skip**

```python
def is_structured_content(text: str) -> bool:
    lines = text.strip().splitlines()
    code_or_table_lines = sum(
        1 for l in lines
        if l.startswith("```") or l.startswith("    ") or l.startswith("|")
    )
    return code_or_table_lines / max(len(lines), 1) > 0.6
```

If `is_structured_content` is true, add `"structured_content": true` to the Qdrant
payload. The retriever can then de-prioritise these chunks (lower `score_threshold`
weight) or apply a post-retrieval reranker that penalises structured-only results.

Do **not** skip these chunks — a user asking "what exercises are in a PPL split?"
needs the table content.

---

### Complete chunking decision tree

```
ParsedChunk
     │
     ├─ token_count < 50  ──► merge with next sibling
     │                        (last section → merge with previous)
     │
     ├─ token_count ≤ 512 ──► yield as-is
     │                        (annotate if mostly code/table)
     │
     └─ token_count > 512 ──► sliding-window split
                               window=512, overlap=64
                               sub-indexed as "{index}.0", "{index}.1", ...
```

### Ingest log with edge case reporting

```
[INFO] rag.chunker  total_parsed=104
[INFO] rag.chunker  merged_short=3   split_long=4   structured=2   normal=95
```

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
