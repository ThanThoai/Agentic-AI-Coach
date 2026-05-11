# Retrieval & Generation

**Component of:** Feature 1 — Fitness Knowledge RAG
**Last updated:** 2026-05-11

---

## Responsibility

This component owns the **online, per-request pipeline**: embedding the user's question,
searching Qdrant for relevant chunks, assembling a prompt, calling the LLM, and formatting
the final response with source citations.

```
POST /api/v1/rag/query  { "question": "..." }
          │
          ▼  retriever.py
  Embed question         ← same model used during ingestion
          │
          ▼
  Qdrant search          ← top-5 chunks, score ≥ 0.35
          │
          ├─ 0 results ──►  guardrails.py  (out-of-scope, no LLM call)
          │
          ▼  rag.py (route handler)
  Build prompt
          │
          ▼
  LLM call               ← structured JSON output
          │
          ▼
  Map cited_indices → Qdrant payloads
          │
          ▼
  RAGResponse JSON
```

---

## 1. Query embedding

**File:** `backend/app/rag/retriever.py`

The user's question must be embedded with the **same model** that was used during ingestion.
Mixing models produces vectors in different geometric spaces — similarity scores become
meaningless.

```python
async def embed_query(question: str, provider: BaseLLMProvider) -> list[float]:
    vectors = await provider.embed([question])
    return vectors[0]
```

The active embedding model is recorded in a Qdrant collection alias or a metadata point
at ingest time. The retriever validates on startup that the configured model matches
what was used to build the index.

---

## 2. Vector search

**File:** `backend/app/rag/retriever.py`

```python
results: list[SearchResult] = await qdrant.search(
    query_vector = question_embedding,
    limit        = 5,
    score_threshold = 0.35,
)
```

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `limit` | 5 | Provides enough context without overloading the prompt; the top-5 chunks for fitness questions are typically all from closely related sections |
| `score_threshold` | 0.35 | Empirical floor for meaningful topical overlap; see calibration note below |

### Score threshold calibration

The threshold of **0.35** is a conservative starting estimate based on the expected
distribution of cosine similarity scores:

```
Clearly in-scope questions vs fitness corpus:    score ≈ 0.45 – 0.85
Ambiguous / general health questions:            score ≈ 0.30 – 0.50
Completely off-topic (weather, coding, etc.):    score ≈ 0.05 – 0.25
```

Before the feature ships, run a calibration exercise:
1. Prepare 15 in-scope questions (expected to return results)
2. Prepare 10 out-of-scope questions (expected to return nothing)
3. Record max similarity score for each query against the indexed corpus
4. Choose threshold = midpoint of the gap between the two distributions

If the gap is small (< 0.05), fall back to the LLM-only out-of-scope strategy (guardrails layer 2).

### What `SearchResult` contains

```python
@dataclass
class SearchResult:
    id:      str
    score:   float
    payload: dict   # source_file, doc_title, section_title, chunk_index, text
```

---

## 3. Prompt construction

**File:** `backend/app/rag/retriever.py` (context builder) + `app/api/v1/rag.py` (assembler)

The prompt has three parts: **system**, **context**, and **user question**.

### System prompt

```
You are a fitness coach assistant. Answer questions using ONLY the information
provided in the numbered context sections below.

Rules:
1. Base every claim on the context. Cite sources using [N] inline.
2. If the context does not contain enough information to answer, say:
   "I don't have specific information about that in my knowledge base."
3. If the question is not about fitness, training, exercise, or nutrition, say:
   "This question is outside my fitness knowledge scope."
4. Do not use external knowledge beyond what is in the context.
5. Return your response as JSON: { "answer": "...", "cited_indices": [1, 3] }
```

The system prompt is eligible for **Anthropic prompt caching** (`cache_control: ephemeral`).
Since it never changes between requests, it will be cached after the first call,
saving ~70% of system-prompt tokens on subsequent requests.

### Context block

Each retrieved chunk is formatted with its index number and source attribution:

```
[1] Source: Progressive Overload > Rate of Progression (08-progressive-overload.md)
────────────────────────────────────────────────────────
## Rate of Progression
- **Beginners**: Can add weight almost every session (newbie gains)
- **Intermediate**: Weekly or biweekly progression
- **Advanced**: Monthly or per training block (mesocycle)

[2] Source: Progressive Overload > Double Progression Method (08-progressive-overload.md)
────────────────────────────────────────────────────────
## Double Progression Method
A practical approach for most trainees:
1. Pick a rep range (e.g., 8-12 reps)
...
```

Chunks are ordered **by score descending** so the LLM sees the most relevant
information first. Experiments with GPT and Claude show that information position
matters — highest-relevance content placed first consistently yields better answers.

### User question

```
Question: How often should a beginner add weight to their lifts?
```

### Full prompt token estimate

```
System prompt:    ~250 tokens (cached after first call)
5 context chunks: ~200 tokens each = ~1000 tokens
User question:    ~20 tokens
─────────────────────────────
Total input:      ~1270 tokens
Cached (Anthropic): ~1250 tokens saved on repeat calls
```

---

## 4. LLM call

**File:** `backend/app/api/v1/rag.py`

```python
response = await llm_provider.complete(
    messages = [LLMMessage(role="user", content=question)],
    system   = full_system_with_context,
    max_tokens  = 512,
    temperature = 0.2,   # low temperature for factual, grounded answers
)
```

**Temperature 0.2:** RAG answers should be grounded and consistent, not creative.
Low temperature reduces hallucination risk and produces more deterministic outputs.

**max_tokens 512:** Fitness answers rarely need more than 300–400 tokens. Capping at
512 prevents runaway generation while leaving headroom for thorough answers.

---

## 5. Response parsing and source mapping

The LLM is expected to return JSON:

```json
{
  "answer": "As a beginner, you can add weight almost every session [1]. Use the double progression method: pick a rep range, add reps until you hit the ceiling, then add weight [2].",
  "cited_indices": [1, 2]
}
```

### Parsing strategy

```python
import json, re

def parse_llm_output(raw: str, chunks: list[SearchResult]) -> tuple[str, list[int]]:
    # Attempt JSON parse
    try:
        data = json.loads(raw.strip())
        return data["answer"], data.get("cited_indices", [])
    except (json.JSONDecodeError, KeyError):
        # Fallback: treat entire response as answer, cite all chunks conservatively
        return raw.strip(), list(range(1, len(chunks) + 1))
```

The fallback is **conservative**: it attributes all retrieved chunks as sources rather
than dropping attribution entirely. This is safer than claiming no sources were used.

### Index → source mapping

`cited_indices` uses **1-based numbering** matching the `[N]` labels in the prompt.
The API layer maps each cited index back to the corresponding `SearchResult` payload:

```python
cited_sources = [
    RAGSource(
        doc_title     = chunks[i - 1].payload["doc_title"],
        section_title = chunks[i - 1].payload["section_title"],
        source_file   = chunks[i - 1].payload["source_file"],
        score         = chunks[i - 1].score,
        excerpt       = chunks[i - 1].payload["text"][:200] + "...",
    )
    for i in cited_indices
    if 1 <= i <= len(chunks)
]
```

The server **never trusts the LLM to produce source metadata** — it only trusts the
index numbers. All doc titles, filenames, and scores come from the pre-fetched Qdrant
results, preventing hallucinated citations.

---

## 6. API contract

### Request

```
POST /api/v1/rag/query
Authorization: Bearer <token>
Content-Type: application/json

{
  "question":    "How do I progress on bench press as an intermediate lifter?",
  "max_sources": 5    // optional, default 5, max 5
}
```

### Response — in scope

```json
{
  "answer": "As an intermediate lifter, expect to progress weekly or biweekly [1]. The double progression method works well: pick a rep range (e.g., 8–12), add reps each session until you hit the ceiling, then increase the weight [2].",
  "in_scope": true,
  "sources": [
    {
      "doc_title":     "Progressive Overload",
      "section_title": "Rate of Progression",
      "source_file":   "08-progressive-overload.md",
      "score":         0.82,
      "excerpt":       "Intermediate: Weekly or biweekly progression..."
    },
    {
      "doc_title":     "Progressive Overload",
      "section_title": "Double Progression Method",
      "source_file":   "08-progressive-overload.md",
      "score":         0.76,
      "excerpt":       "A practical approach for most trainees: Pick a rep range..."
    }
  ],
  "model":   "claude-sonnet-4-6",
  "usage": {
    "prompt_tokens":      612,
    "completion_tokens":  118,
    "cache_read_tokens":  590
  }
}
```

### Response — out of scope

```json
{
  "answer":   "I can only answer questions about fitness, training, and nutrition. Your question appears to be outside that scope.",
  "in_scope": false,
  "sources":  [],
  "model":    null,
  "usage":    null
}
```

### Pydantic schemas

```python
# app/schemas/rag.py

class RAGQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question:    str = Field(min_length=3, max_length=1000)
    max_sources: int = Field(default=5, ge=1, le=5)

class RAGSource(BaseModel):
    doc_title:     str
    section_title: str
    source_file:   str
    score:         float
    excerpt:       str

class RAGResponse(BaseModel):
    answer:   str
    in_scope: bool
    sources:  list[RAGSource]
    model:    str | None
    usage:    TokenUsage | None
```

---

## 7. Request flow sequence diagram

```
Client          API Route       Retriever       Qdrant          LLM
  │                 │               │               │              │
  │  POST /query    │               │               │              │
  │────────────────►│               │               │              │
  │                 │ embed_query() │               │              │
  │                 │──────────────►│               │              │
  │                 │               │  search()     │              │
  │                 │               │──────────────►│              │
  │                 │               │  results[]    │              │
  │                 │               │◄──────────────│              │
  │                 │  chunks[]     │               │              │
  │                 │◄──────────────│               │              │
  │                 │                                              │
  │                 │  complete(system+context+question)           │
  │                 │─────────────────────────────────────────────►│
  │                 │  { answer, cited_indices }                   │
  │                 │◄─────────────────────────────────────────────│
  │                 │                                              │
  │  RAGResponse    │                                              │
  │◄────────────────│                                              │
```
