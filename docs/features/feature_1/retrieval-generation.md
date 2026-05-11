# Retrieval & Generation

**Component of:** Feature 1 — Fitness Knowledge RAG
**Last updated:** 2026-05-11

---

## Responsibility

This component owns the **online, per-request pipeline**: processing the user's question,
searching Qdrant for relevant chunks, assembling a prompt, calling the LLM, and formatting
the final response with source citations.

Simple questions go through a direct path. Complex, multi-faceted, or comparison questions
are routed through Query Decomposition and Parallel Retrieval before reaching the LLM.

```
POST /api/v1/rag/query  { "question": "..." }
          │
          ▼  Layer 1 guardrails (hard-block, rate limit)
          │
          ▼  query_processor.py
  ┌───────────────────────────────────────────┐
  │             Query Processing              │
  │  Classification → Rewriting/Decomposition │
  └───────────────────────────────────────────┘
          │                │
     SIMPLE path      COMPLEX/COMPARISON path
          │                │
          ▼                ▼ (parallel)
  single rewritten    sub-questions × hybrid search
  hybrid search           │
          │           Merge + deduplicate
          └──────────────►│
                          ▼
                  top-5 chunks (score ≥ 0.35)
                          │
                ├─ 0 results ──► out-of-scope
                          │
                          ▼
                  Build prompt + LLM call
                          │
                          ▼
                  Layer 3 output filter
                          │
                          ▼
                     RAGResponse
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

No contextual prefix is added to query embeddings (unlike ingestion, which uses
`"Document: X | Section: Y | ..."` — see chunking-embedding.md). The asymmetry is
intentional: the model learns to align bare questions with prefixed passage vectors.

---

## 2. Query processing

**File:** `backend/app/rag/query_processor.py`

Raw questions often underperform in retrieval:
- **Short queries** miss synonyms and domain vocabulary
- **Multi-part questions** spread their signal across topics — no single vector captures all sub-intents
- **Comparison questions** need independent evidence for each option

Query processing resolves these problems before any vector search happens.

### 2a. Query Classification

Classification decides which retrieval path to take.

```
             ┌───────────────────────────────────────────────────┐
             │              Query Classification                  │
             │                                                    │
             │   SIMPLE      →  rewrite → single hybrid search   │
             │   COMPLEX     →  decompose → parallel search       │
             │   COMPARISON  →  decompose → parallel search       │
             └───────────────────────────────────────────────────┘
```

**Step 1 — heuristics (0 ms, 0 tokens):** catch clear-cut cases before any LLM call.

```python
import re
from typing import Literal

QueryType = Literal["SIMPLE", "COMPLEX", "COMPARISON"]

_COMPARISON_SIGNALS = re.compile(
    r"\b(vs\.?|versus|compare|comparison|difference between|better than|which is better|"
    r"or\b.{3,40}\bor\b)\b",
    re.IGNORECASE,
)
_COMPLEXITY_SIGNALS = re.compile(
    r"\b(and (also|how|what|when|why)|both .{3,30} and|additionally|as well as|"
    r"at the same time|while also)\b",
    re.IGNORECASE,
)

def classify_query_heuristic(question: str) -> QueryType | None:
    """Fast heuristic pre-filter. Returns None when LLM classification is needed."""
    if _COMPARISON_SIGNALS.search(question):
        return "COMPARISON"
    if len(question) > 120 and _COMPLEXITY_SIGNALS.search(question):
        return "COMPLEX"
    if len(question) <= 80:
        return "SIMPLE"   # short questions rarely need decomposition
    return None           # ambiguous — escalate to LLM
```

**Step 2 — LLM classifier (invoked only when heuristics return `None`):**

```
You are a fitness question classifier. Classify the query as exactly one of:

  SIMPLE      — Single focused question answerable from one topic area.
                A question is SIMPLE when it asks about one concept, one technique,
                or one programming variable.

  COMPLEX     — Multi-part question requiring information from more than one
                distinct topic. Look for conjunctions that join two independent
                sub-questions (e.g. "... and how ...", "... as well as ...").

  COMPARISON  — Asks to evaluate, rank, or contrast two or more options.
                Look for "vs", "versus", "better than", "or ... or", "which".

---

Examples:

Query: "How many sets per week should I do for chest hypertrophy?"
{"type": "SIMPLE", "reason": "Single focused question about volume for one muscle group"}

Query: "What does RPE mean in strength training?"
{"type": "SIMPLE", "reason": "Definitional question about a single concept"}

Query: "Should I do cardio on rest days?"
{"type": "SIMPLE", "reason": "Single programming question, no competing sub-topics"}

Query: "How should I structure my PPL split and what intensity should I train at for hypertrophy?"
{"type": "COMPLEX", "reason": "Two independent sub-topics: split structure and training intensity"}

Query: "What should my macros be and how should I time my meals around training?"
{"type": "COMPLEX", "reason": "Macro targets and meal timing are separate retrieval targets"}

Query: "How do I fix my squat depth and what accessories can help bring it up?"
{"type": "COMPLEX", "reason": "Technique correction and accessory programming require different knowledge"}

Query: "Is PPL or Upper/Lower better for an intermediate lifter building muscle?"
{"type": "COMPARISON", "reason": "Contrasting two split options for the same goal"}

Query: "Creatine monohydrate vs HMB — which is more effective for muscle gain?"
{"type": "COMPARISON", "reason": "Direct head-to-head comparison of two supplements"}

Query: "Should I do 5×5 or 3×10 for building strength?"
{"type": "COMPARISON", "reason": "Evaluating two rep-range protocols against each other"}

---

Return JSON only: {"type": "SIMPLE" | "COMPLEX" | "COMPARISON", "reason": "<one sentence>"}

Query: {question}
```

```python
async def classify_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> QueryType:
    fast = classify_query_heuristic(question)
    if fast is not None:
        return fast
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_CLASSIFIER_SYSTEM_PROMPT,
        max_tokens=60,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json_block(resp.content))
        t = data.get("type", "SIMPLE")
        return t if t in ("SIMPLE", "COMPLEX", "COMPARISON") else "SIMPLE"
    except Exception:
        return "SIMPLE"   # fail-safe: degrade to simple path
```

**Cost:** heuristics cover ~70% of queries at 0 cost. LLM classification costs ~60 tokens
(~$0.000048 with Haiku) and is only invoked for the remaining ~30%.

---

### 2b. Query Rewriting

Applied to **SIMPLE** queries — rewrites the user's raw question into a richer search
string that improves recall by expanding abbreviations, adding synonyms, and surfacing
implicit domain context.

```
Input:  "bench press stall"
Output: "bench press plateau strength stall not progressing barbell chest powerlifting"

Input:  "best PPL"
Output: "Push Pull Legs PPL workout split program structure frequency hypertrophy strength"
```

**Why rewriting helps:**
- Users write in natural language; the corpus uses domain-specific terminology
- Short queries (< 60 chars) miss many semantically related chunks
- Expansion increases the chance the sparse (BM25) component finds term-level matches

```
You are a search query optimizer for a fitness coaching knowledge base.
Rewrite the user's question into a richer search query:
- Expand abbreviations (PPL → Push Pull Legs, OHP → overhead press, RDL → Romanian deadlift)
- Add fitness synonyms and related terms (hypertrophy → muscle growth, volume)
- Make implicit context explicit ("bench press" → "bench press barbell technique form chest")
- Keep the rewrite under 150 characters

Return only the rewritten query string, no explanation, no quotes.

---

Examples:

Question: "OHP form tips"
overhead press barbell technique form shoulder press mechanics cues proper positioning stability

Question: "DOMS after leg day"
delayed onset muscle soreness DOMS causes treatment recovery muscle pain after workout squat legs

Question: "best PPL"
Push Pull Legs PPL workout split program structure frequency hypertrophy strength intermediate

Question: "progressive overload bench"
progressive overload bench press barbell strength programming adding weight reps sets progression method

Question: "chest won't grow"
chest pectoral muscle growth plateau hypertrophy technique volume progressive overload exercises stagnation

Question: "training frequency"
optimal training frequency sessions per week muscle group hypertrophy recovery stimulus adaptation

Question: "RDL how to"
Romanian deadlift RDL technique form hip hinge hamstring stretch posterior chain barbell execution cues

---

Question: {question}
```

```python
async def rewrite_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> str:
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_REWRITE_SYSTEM_PROMPT,
        max_tokens=80,
        temperature=0.0,
        model=model,
    )
    rewritten = resp.content.strip().strip('"')
    # Guard: if rewrite looks broken (empty or too long), fall back to original
    if not rewritten or len(rewritten) > 300:
        return question
    return rewritten
```

**Cost:** ~80 tokens per call (~$0.000064 with Haiku). Skip rewriting for questions
already > 80 chars — they are verbose enough to provide good recall on their own.

---

### 2c. Query Decomposition

Applied to **COMPLEX** and **COMPARISON** queries — breaks the question into 2–3
focused sub-questions that can each be retrieved independently.

```
Input:  "What's the best workout split for hypertrophy and how much volume
         should I do per muscle group per week?"
Output: [
  "best workout split for hypertrophy PPL upper lower full body",
  "optimal training volume sets per muscle group per week hypertrophy"
]

Input:  "Is PPL or Upper/Lower better for an intermediate lifter?"
Output: [
  "Push Pull Legs PPL program intermediate lifter pros cons",
  "Upper Lower split intermediate lifter benefits structure"
]
```

```
You are a query decomposer for a fitness coaching knowledge base.
Break the user's question into 2–3 focused sub-questions that can each be
answered independently from the knowledge base.

Rules:
- Each sub-question must be independently answerable
- Expand abbreviations in every sub-question
- For COMPARISON questions: one sub-question per option being compared
- For COMPLEX questions: one sub-question per distinct topic or concern
- Do not produce more than 3 sub-questions

---

Examples:

Question: "How should I structure my PPL split and what intensity should I train at for hypertrophy?"
{"sub_questions": [
  "Push Pull Legs PPL workout split structure sessions per week frequency hypertrophy",
  "training intensity percentage 1RM RPE range optimal muscle growth hypertrophy"
]}

Question: "What should my macros be and how should I time my meals around training?"
{"sub_questions": [
  "macronutrients protein carbohydrate fat ratio targets muscle building body composition",
  "meal timing pre-workout post-workout nutrition performance recovery"
]}

Question: "How do I fix my squat depth and what accessory exercises can help improve it?"
{"sub_questions": [
  "squat depth improvement ankle hip mobility flexibility technique cues drills",
  "accessory exercises improve squat depth goblet squat box squat pause squat"
]}

Question: "Is free weights or machines better for building muscle?"
{"sub_questions": [
  "free weights barbell dumbbell muscle hypertrophy advantages compound movement stability",
  "resistance machines muscle hypertrophy advantages isolation stability range of motion"
]}

Question: "Should I use creatine or protein powder as my first supplement?"
{"sub_questions": [
  "creatine monohydrate benefits muscle building strength performance beginner supplement",
  "protein powder whey supplement muscle synthesis recovery daily protein intake"
]}

Question: "Which is better for fat loss and muscle retention — HIIT or steady state cardio?"
{"sub_questions": [
  "HIIT high intensity interval training fat loss muscle retention caloric expenditure",
  "steady state cardio LISS fat loss muscle preservation aerobic base caloric expenditure"
]}

---

Return JSON only: {"sub_questions": ["...", "...", "..."]}

Question: {question}
```

```python
async def decompose_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> list[str]:
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_DECOMPOSE_SYSTEM_PROMPT,
        max_tokens=200,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json_block(resp.content))
        subs = [s.strip() for s in data.get("sub_questions", []) if s.strip()]
        if 1 <= len(subs) <= 3:
            return subs
    except Exception:
        pass
    return [question]   # fall back to original question as a single sub-query
```

**Cost:** ~200 tokens per call (~$0.00016 with Haiku). Only invoked for COMPLEX /
COMPARISON queries (~20% of traffic by rough estimate).

---

### 2d. Combined query processing entry point

```python
async def process_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    classifier_model: str | None = None,
    rewrite_model: str | None = None,
) -> tuple[QueryType, list[str]]:
    """
    Classify the query and return (query_type, list_of_search_strings).
    SIMPLE  → [rewritten_question]
    COMPLEX / COMPARISON → [sub_q1, sub_q2, ...]
    """
    query_type = await classify_query(question, provider, model=classifier_model)

    if query_type == "SIMPLE":
        rewritten = await rewrite_query(question, provider, model=rewrite_model)
        return query_type, [rewritten]

    sub_questions = await decompose_query(question, provider, model=rewrite_model)
    return query_type, sub_questions
```

---

## 3. Retrieval

**File:** `backend/app/rag/retriever.py`

### 3a. Hybrid search (single query)

Each search string goes through hybrid dense + sparse RRF retrieval (see
`QdrantVectorDB.hybrid_search`):

```python
from app.rag.sparse import build_sparse_vector

async def hybrid_search_one(
    query_str: str,
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    limit: int = 5,
    score_threshold: float = 0.35,
) -> list[SearchResult]:
    dense_vec = await embed_query(query_str, provider)
    sparse_vec = build_sparse_vector(query_str)
    return await qdrant.hybrid_search(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        limit=limit,
        prefetch_limit=20,
    )
```

### 3b. Parallel retrieval (multiple sub-queries)

For COMPLEX and COMPARISON queries, all sub-queries run concurrently:

```python
import asyncio

async def parallel_hybrid_search(
    sub_questions: list[str],
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    limit_per_query: int = 5,
    final_limit: int = 5,
    score_threshold: float = 0.35,
) -> list[SearchResult]:
    # Sparse vectors are CPU-only (fastembed BM25) — build synchronously
    sparse_vecs = [build_sparse_vector(q) for q in sub_questions]
    # Embed all sub-questions concurrently (each call hits the embedding API)
    dense_vecs: list[list[float]] = await asyncio.gather(
        *[embed_query(q, provider) for q in sub_questions]
    )

    # Run all hybrid searches concurrently
    results_per_query: list[list[SearchResult]] = await asyncio.gather(*[
        qdrant.hybrid_search(
            dense_vector=dense,
            sparse_vector=sparse,
            limit=limit_per_query,
        )
        for dense, sparse in zip(dense_vecs, sparse_vecs)
    ])

    # Merge, deduplicate by chunk id, sort by best score seen
    best_score: dict[str, float] = {}
    by_id: dict[str, SearchResult] = {}
    for results in results_per_query:
        for r in results:
            if r.id not in best_score or r.score > best_score[r.id]:
                best_score[r.id] = r.score
                by_id[r.id] = r

    merged = sorted(by_id.values(), key=lambda r: r.score, reverse=True)
    return [r for r in merged if r.score >= score_threshold][:final_limit]
```

**Why concurrent embedding matters:** embedding API calls take ~100–200 ms each.
Running 3 sub-questions sequentially = 300–600 ms. Running them with `asyncio.gather`
collapses that to ~100–200 ms — the latency of a single call.

### 3c. Unified retrieval entry point

```python
async def retrieve(
    sub_questions: list[str],
    query_type: QueryType,
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    max_sources: int = 5,
) -> list[SearchResult]:
    if query_type == "SIMPLE":
        return await hybrid_search_one(
            sub_questions[0], provider, qdrant, limit=max_sources
        )
    return await parallel_hybrid_search(
        sub_questions, provider, qdrant,
        limit_per_query=max_sources,
        final_limit=max_sources,
    )
```

### 3d. Score threshold calibration

| Query type | Expected score range (in-scope) | Expected score range (off-topic) |
|------------|--------------------------------|----------------------------------|
| Direct term match | 0.55 – 0.85 | — |
| Paraphrase / synonym | 0.40 – 0.65 | — |
| Off-topic (weather, coding) | — | 0.05 – 0.25 |
| Ambiguous general health | 0.25 – 0.45 | — |

Threshold **0.35** sits at the boundary between ambiguous health and off-topic.
Calibrate with a 30-question labelled set (20 in-scope, 10 out-of-scope) before
shipping and adjust if the gap is < 0.05.

---

### 3e. Deduplication + Re-ranking

**File:** `backend/app/rag/retriever.py`

After parallel retrieval, the candidate pool contains chunks from multiple sub-query
result lists. Two problems must be addressed before prompt assembly:

1. **Duplicates** — the same chunk may appear in several sub-query results with
   different scores. Keep it once, carrying the highest raw score.
2. **Ranking quality** — sorting by max score across sub-queries is crude. A chunk
   that ranked #1 in every sub-query's result list should score higher than a chunk
   that ranked #1 in only one list at a marginally higher score.

#### Reciprocal Rank Fusion (RRF) across sub-query results

RRF promotes chunks that appear consistently across multiple sub-queries:

```
score_RRF(chunk) = Σ  1 / (k + rank_i(chunk))
                  i∈sub_queries
```

`k = 60` is the standard smoothing constant. A chunk ranked #1 in two lists scores
`2 / (60 + 1) ≈ 0.033`; a chunk ranked #1 in only one list scores `1 / 61 ≈ 0.016`.

```python
def rrf_merge(
    results_per_query: list[list[SearchResult]],
    k: int = 60,
    final_limit: int = 5,
    score_threshold: float = 0.35,
) -> list[SearchResult]:
    """RRF across multiple sub-query result lists. Deduplicates as a side-effect."""
    rrf_scores: dict[str, float] = {}
    by_id: dict[str, SearchResult] = {}

    for results in results_per_query:
        for rank, r in enumerate(results, start=1):
            rrf_scores[r.id] = rrf_scores.get(r.id, 0.0) + 1.0 / (k + rank)
            if r.id not in by_id or r.score > by_id[r.id].score:
                by_id[r.id] = r  # keep for payload access; store best raw score

    ranked_ids = sorted(
        [cid for cid in by_id if by_id[cid].score >= score_threshold],
        key=lambda cid: rrf_scores[cid],
        reverse=True,
    )
    return [by_id[cid] for cid in ranked_ids[:final_limit]]
```

For **SIMPLE** queries (single sub-question), `results_per_query` has one list —
RRF degenerates to a simple score sort, identical to what `parallel_hybrid_search`
already does. No special-casing needed.

#### Diversity filter

For COMPLEX / COMPARISON queries, pure score-based ranking can flood the context
with chunks from a single document, leaving little room for the second topic. The
diversity filter caps the number of chunks from any one source file:

```python
def apply_diversity_filter(
    chunks: list[SearchResult],
    max_per_source: int = 2,
) -> list[SearchResult]:
    """
    Prevent any single source document from occupying more than max_per_source
    slots in the final context window.
    Applied after RRF; order is preserved.
    """
    counts: dict[str, int] = {}
    result: list[SearchResult] = []
    for chunk in chunks:
        src = chunk.payload.get("source_file", "")
        if counts.get(src, 0) < max_per_source:
            result.append(chunk)
            counts[src] = counts.get(src, 0) + 1
    return result
```

**When each step applies:**

| Query type | Deduplication | RRF re-ranking | Diversity filter |
|------------|--------------|---------------|-----------------|
| `SIMPLE` | Not needed (1 list) | Score sort only | Not applied |
| `COMPLEX` | Yes | Yes | Yes (`max_per_source=2`) |
| `COMPARISON` | Yes | Yes | Yes (`max_per_source=2`) |

---

## 4. Context Assembly

**File:** `backend/app/rag/retriever.py`

Context assembly converts the ranked, deduplicated `SearchResult` list into a
formatted string that fits within the prompt's token budget.

### Token budget

```python
import tiktoken

_TOKENIZER = tiktoken.get_encoding("cl100k_base")
MAX_CONTEXT_TOKENS = 1200   # hard cap for the chunk block

def _count_tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text))
```

| Component | Tokens | Cached? |
|-----------|--------|---------|
| System prompt | ~250 | Yes (Anthropic `cache_control: ephemeral`) |
| Context block (up to 5 chunks) | ≤ 1 200 | No |
| Multi-topic header (COMPLEX / COMPARISON) | +20 | No |
| Synthesis instruction (COMPLEX / COMPARISON) | +25 | No |
| User question | ~20 | No |
| **Total** | **≤ 1 520** | |

### Chunk formatting

```python
def _format_chunk(index: int, chunk: SearchResult) -> str:
    p = chunk.payload
    header = (
        f"[{index}] Source: {p.get('doc_title', '?')} > "
        f"{p.get('section_title', '?')} ({p.get('source_file', '?')})"
    )
    separator = "─" * 56
    return f"{header}\n{separator}\n{p.get('text', '')}"
```

Rendered output:

```
[1] Source: Progressive Overload > Rate of Progression (08-progressive-overload.md)
────────────────────────────────────────────────────────────────
- Beginners: Can add weight almost every session (newbie gains)
- Intermediate: Weekly or biweekly progression
- Advanced: Monthly or per training block (mesocycle)

[2] Source: Workout Splits > Push-Pull-Legs Structure (14-workout-split-ppl.md)
────────────────────────────────────────────────────────────────
A PPL split trains each muscle group twice per week with focused sessions...
```

### Assembly with token guard

```python
def assemble_context(
    chunks: list[SearchResult],
    query_type: QueryType,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> tuple[str, list[SearchResult]]:
    """
    Format chunks into context string; trim to stay within max_tokens.
    Returns (context_string, list_of_chunks_actually_included).
    """
    entries: list[str] = []
    used: list[SearchResult] = []
    total = 0

    for i, chunk in enumerate(chunks, start=1):
        entry = _format_chunk(i, chunk)
        t = _count_tokens(entry)
        if total + t > max_tokens:
            break           # stop before exceeding budget
        entries.append(entry)
        used.append(chunk)
        total += t

    block = "\n\n".join(entries)

    if query_type in ("COMPLEX", "COMPARISON"):
        note = (
            "Note: the following context covers multiple sub-topics related to "
            "your question. Use all relevant sections when composing your answer.\n\n"
        )
        block = note + block

    return block, used
```

Chunks are passed in **score-descending order** so the most relevant content is
always included when the budget is tight and trailing chunks must be dropped.

---

## 5. Generation

**File:** `backend/app/api/v1/rag.py`

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

Eligible for **Anthropic prompt caching** — the static system prompt is wrapped
with `cache_control: ephemeral`, saving ~70 % of its tokens on repeat calls.

### COMPLEX / COMPARISON synthesis instruction

For multi-topic queries, a synthesis instruction is appended to the system prompt
before the context block. It tells the LLM to integrate evidence across topics
rather than answering each sub-topic sequentially:

```python
SYNTHESIS_INSTRUCTION = (
    "\n\nThe context above covers multiple sub-topics. Synthesise a unified answer "
    "that addresses all parts of the question. Cite sources for each distinct "
    "sub-claim using [N] notation."
)
```

### Generation call

```python
async def generate(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
) -> LLMResponse:
    system = GENERATION_SYSTEM_PROMPT
    if query_type in ("COMPLEX", "COMPARISON"):
        system += SYNTHESIS_INSTRUCTION
    full_system = system + "\n\n" + context

    return await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=full_system,
        max_tokens=512,
        temperature=0.2,
    )
```

**temperature=0.2** — low for factual, grounded answers; higher values increase
hallucination risk on RAG tasks.

**max_tokens=512** — typical fitness answers run 200–400 tokens; 512 gives headroom
for longer synthesis on COMPLEX queries without runaway generation.

### Streaming variant

For endpoints that stream the answer token-by-token (e.g. chat UI):

```python
async def generate_stream(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
) -> AsyncIterator[str]:
    system = GENERATION_SYSTEM_PROMPT
    if query_type in ("COMPLEX", "COMPARISON"):
        system += SYNTHESIS_INSTRUCTION
    full_system = system + "\n\n" + context

    async for token in provider.stream(
        messages=[LLMMessage(role="user", content=question)],
        system=full_system,
        max_tokens=512,
        temperature=0.2,
    ):
        yield token
```

Streaming does not change the prompt or parameters — only whether tokens are
buffered and returned at once or yielded incrementally.

---

## 6. Response parsing and source mapping

The LLM is expected to return JSON:

```json
{
  "answer": "As a beginner, you can add weight almost every session [1]. Use the double progression method: pick a rep range, add reps until you hit the ceiling, then add weight [2].",
  "cited_indices": [1, 2]
}
```

### Parsing strategy

```python
def parse_llm_output(raw: str, num_chunks: int) -> tuple[str, list[int]]:
    try:
        data = json.loads(raw.strip())
        return data["answer"], [int(i) for i in data.get("cited_indices", [])]
    except (json.JSONDecodeError, KeyError, ValueError):
        return raw.strip(), list(range(1, num_chunks + 1))
```

The fallback is conservative: cite all retrieved chunks rather than claiming no sources.

### Index → source mapping

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

## 7. API contract

### Request

```
POST /api/v1/rag/query
Authorization: Bearer <token>
Content-Type: application/json

{
  "question":    "What's the difference between PPL and Upper/Lower for hypertrophy?",
  "max_sources": 5
}
```

### Response — in scope

```json
{
  "answer": "PPL trains each muscle group twice per week with focused sessions [1]. Upper/Lower also hits each muscle twice but pairs antagonist muscle groups [2]. For hypertrophy, both are effective; PPL gives more per-session volume per muscle, while Upper/Lower improves recovery balance [1][2].",
  "in_scope": true,
  "intent": "COMPARISON",
  "sources": [
    {
      "doc_title":     "Workout Splits",
      "section_title": "Push-Pull-Legs Structure",
      "source_file":   "14-workout-split-ppl.md",
      "score":         0.81,
      "excerpt":       "A PPL split trains each muscle group twice per week..."
    },
    {
      "doc_title":     "Workout Splits",
      "section_title": "Upper/Lower Structure",
      "source_file":   "14-workout-split-ppl.md",
      "score":         0.76,
      "excerpt":       "Upper/Lower pairs push and pull movements..."
    }
  ],
  "model": "claude-sonnet-4-6",
  "usage": {
    "prompt_tokens":      1320,
    "completion_tokens":  148,
    "cache_read_tokens":  1280
  }
}
```

### Response — out of scope

```json
{
  "answer":   "I can only answer questions about fitness, training, and nutrition. Your question appears to be outside that scope.",
  "in_scope": false,
  "intent":   null,
  "sources":  [],
  "model":    null,
  "usage":    null
}
```

### Pydantic schemas

```python
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
    intent:   str | None       # SIMPLE / COMPLEX / COMPARISON
    sources:  list[RAGSource]
    model:    str | None
    usage:    TokenUsage | None
```

---

## 8. Latency and cost breakdown

### Per-request latency (typical)

| Step | SIMPLE path | COMPLEX / COMPARISON path |
|------|------------|--------------------------|
| Query classification (heuristic) | ~0 ms | ~0 ms |
| Query classification (LLM) | 0 ms (heuristic hit) | ~150 ms (30% of requests) |
| Query rewriting | ~150 ms | — |
| Query decomposition | — | ~200 ms |
| Embedding (asyncio.gather) | ~150 ms | ~150 ms (concurrent) |
| Hybrid search (Qdrant) | ~10 ms | ~10 ms (concurrent, dominated by 1 call) |
| Deduplication + RRF re-ranking | ~1 ms | ~2 ms |
| Diversity filter | — | ~1 ms |
| Context assembly (tiktoken) | ~5 ms | ~5 ms |
| Guardrail Layer 2 (if triggered) | ~200 ms | ~200 ms |
| LLM generation | ~800 ms | ~1 000 ms (longer synthesis) |
| Layer 3 output filter | ~5 ms | ~5 ms |
| **Total (p50 estimate)** | **~1 110 ms** | **~1 515 ms** |

Embedding is the dominant non-LLM cost. Parallel retrieval keeps it flat regardless
of how many sub-questions are produced by decomposition.

### Per-request token cost (Haiku for processing, Sonnet for generation)

| Step | Tokens | Cost (Haiku) |
|------|--------|-------------|
| Query classification (LLM, 30% of requests) | ~60 | ~$0.000048 × 0.3 = $0.000014 |
| Query rewriting (SIMPLE, ~70% of requests) | ~80 | ~$0.000064 × 0.7 = $0.000045 |
| Query decomposition (COMPLEX, ~20%) | ~200 | ~$0.00016 × 0.2 = $0.000032 |
| Layer 2 guardrails (10% of requests) | ~150 | ~$0.00012 × 0.1 = $0.000012 |
| **Processing subtotal (avg)** | | **~$0.0001** |
| LLM generation (Sonnet, every request) | ~1 300 in + ~150 out | ~$0.006 |
| **Total per request (avg)** | | **~$0.006** |

---

## 9. Full request flow sequence diagram

```
Client        API Route     QueryProcessor    Retriever       Qdrant       Haiku     Sonnet
  │               │               │               │              │            │          │
  │  POST /query  │               │               │              │            │          │
  │──────────────►│               │               │              │            │          │
  │               │ classify()    │               │              │            │          │
  │               │──────────────►│               │              │            │          │
  │               │               │── heuristic ──┤              │            │          │
  │               │               │   (or Haiku)──┼──────────────┼───────────►│          │
  │               │               │               │              │◄───────────│          │
  │               │               │               │              │  type      │          │
  │               │ rewrite() or  │               │              │            │          │
  │               │ decompose()   │               │              │            │          │
  │               │──────────────►│───────────────┼──────────────┼───────────►│          │
  │               │               │               │              │◄───────────│          │
  │               │               │  sub_questions│              │            │          │
  │               │               │               │              │            │          │
  │               │  retrieve()   │               │              │            │          │
  │               │──────────────────────────────►│              │            │          │
  │               │               │               │ embed (×N concurrent)     │          │
  │               │               │               │──────────────┼───────────►│          │
  │               │               │               │◄─────────────┼────────────│          │
  │               │               │               │ hybrid_search (×N concurrent)        │
  │               │               │               │─────────────►│            │          │
  │               │               │               │◄─────────────│            │          │
  │               │               │               │ rrf_merge +  │            │          │
  │               │               │               │ diversity    │            │          │
  │               │               │               │ filter       │            │          │
  │               │               │               │ assemble_context()        │          │
  │               │  chunks[]     │               │              │            │          │
  │               │◄──────────────────────────────│              │            │          │
  │               │                                                            │          │
  │               │  complete(system+context+question)                                   │
  │               │──────────────────────────────────────────────────────────────────────►│
  │               │  { answer, cited_indices }                                            │
  │               │◄──────────────────────────────────────────────────────────────────────│
  │               │                                                                       │
  │  RAGResponse  │                                                                       │
  │◄──────────────│                                                                       │
```

---

## 10. Failure modes and fallbacks

| Failure | Fallback |
|---------|---------|
| Query classification LLM timeout | Default to `SIMPLE` — safe degradation, no user impact |
| Query rewriting returns empty/malformed | Use original question as-is |
| Decomposition returns > 3 sub-questions | Truncate to first 3 |
| Decomposition returns 1 sub-question | Treat as SIMPLE path |
| All parallel searches return 0 results | Return out-of-scope response |
| RRF produces 0 chunks after score threshold filter | Return out-of-scope response (same path as zero search results) |
| Merged result count < 2 | Return what was found, no error |
| Diversity filter reduces pool to < 2 chunks | Return the filtered chunks as-is; 1 chunk is still useful |
| First chunk alone exceeds context budget | Include first chunk only — `assemble_context()` breaks on first iteration |
| LLM output is not valid JSON | `parse_llm_output()` falls back to raw text + cite all chunks |
| LLM cites index out of bounds | Silently drop (bounds check in `filter_output()`) |
