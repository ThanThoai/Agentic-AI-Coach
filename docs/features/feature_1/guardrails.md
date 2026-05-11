# Guardrails

**Component of:** Feature 1 — Fitness Knowledge RAG
**Last updated:** 2026-05-11

---

## Responsibility

Guardrails protect the system from producing incorrect, harmful, or irrelevant outputs.
They operate at multiple layers: before any LLM call (fast, cheap), inside the LLM
prompt (reliable), and after the LLM responds (output validation).

```
Incoming request
      │
      ▼ Layer 0: Input validation (Pydantic)
      ▼ Layer 1: Rate limiting (Redis)
      │
      ▼ Vector search
      │
      ├── score < 0.35 ──► Layer 2a: Similarity gate → immediate rejection
      │
      ▼ Prompt with context
      │
      ▼ LLM call  (Layer 2b: Prompt instruction embedded in system prompt)
      │
      ▼ Layer 3: Output validation (parse, length check)
      │
      ▼ Response returned
```

---

## Layer 0 — Input validation

**Enforced by:** Pydantic schema `RAGQuery`

```python
class RAGQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question:    str = Field(min_length=3, max_length=1000)
    max_sources: int = Field(default=5, ge=1, le=5)
```

| Rule | Constraint | Failure response |
|------|-----------|-----------------|
| Minimum question length | ≥ 3 characters | HTTP 422 |
| Maximum question length | ≤ 1000 characters | HTTP 422 |
| Unknown fields | Rejected | HTTP 422 |
| max_sources range | 1–5 | HTTP 422 |

**Why 1000-character cap?**
Prevents token-abuse attacks where an adversary embeds a very long input to inflate
prompt length and cost. 1000 characters is ≈ 250 tokens, well within what is needed
to ask any fitness question.

---

## Layer 1 — Rate limiting

**Enforced by:** Redis sliding-window middleware

| Endpoint | Limit | Window |
|----------|-------|--------|
| `POST /api/v1/rag/query` | 10 requests | 1 minute per user |

RAG requests are expensive: each involves an embedding call, a Qdrant search, and
an LLM call. 10 req/min per user is generous for interactive use while preventing
abuse.

On limit exceeded, return:

```http
HTTP 429 Too Many Requests
Retry-After: 42
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1746970800

{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Please wait before trying again.",
    "details": { "retry_after_seconds": 42 }
  }
}
```

---

## Layer 2a — Similarity gate (pre-LLM, no cost)

**Enforced by:** `backend/app/rag/retriever.py`

After the vector search, if **no chunk scores ≥ 0.35**, the question is considered
out-of-scope and the request is rejected **without making an LLM call**.

```python
if not results:  # all chunks were below score_threshold=0.35
    return RAGResponse(
        answer   = OUT_OF_SCOPE_MESSAGE,
        in_scope = False,
        sources  = [],
        model    = None,
        usage    = None,
    )
```

```python
OUT_OF_SCOPE_MESSAGE = (
    "I can only answer questions about fitness, training, exercise, and nutrition. "
    "Your question appears to be outside that scope."
)
```

### Why this layer matters

| Question | Max score | Outcome |
|----------|-----------|---------|
| "How do I bench press correctly?" | ~0.78 | Passes → LLM answers |
| "What should I eat before a workout?" | ~0.55 | Passes → LLM answers |
| "Can you help me with my Python code?" | ~0.18 | Rejected → no LLM cost |
| "What's the weather in Hanoi?" | ~0.08 | Rejected → no LLM cost |
| "How do I improve my mental health?" | ~0.32 | Rejected (borderline) |

The similarity gate eliminates the entire class of obviously off-topic queries without
spending any LLM tokens. For a corpus of fitness-only documents, any question about
cooking, finance, technology, news, or general life advice will score far below 0.35.

### Threshold calibration procedure

Before shipping, validate with a labelled question set:

```
1. Collect 20 in-scope questions (variety: form, programming, nutrition, recovery)
2. Collect 15 out-of-scope questions (variety: weather, coding, food recipes, current events)
3. Embed all questions, run Qdrant search, record max_score for each
4. Plot score distributions (in-scope vs out-of-scope)
5. Set threshold = point that minimises (false positives + false negatives)
   Rule of thumb: if distributions overlap, prefer the lower value (fewer false rejections)
```

---

## Layer 2b — Prompt instruction (in-LLM, catches edge cases)

**Enforced by:** system prompt embedded in the LLM call

Even when chunks are retrieved (score ≥ 0.35), the LLM may receive context that does
not actually answer the question — for example, a question about weather that happened
to mention "performance" and matched a training article.

The system prompt includes an explicit instruction:

```
Rules:
...
3. If the question is not about fitness, training, exercise, or nutrition, say:
   "This question is outside my fitness knowledge scope."
4. Do not use external knowledge beyond what is in the context.
   If the provided context does not contain enough information, say:
   "I don't have specific information about that in my knowledge base."
```

### Two distinct refusal messages

| Situation | LLM response |
|-----------|--------------|
| Question is off-topic (non-fitness) | "This question is outside my fitness knowledge scope." |
| Question is fitness-related but not covered in the knowledge base | "I don't have specific information about that in my knowledge base." |

This distinction matters for the user experience: the first tells them the system
can't help with that topic at all; the second tells them the system covers fitness
but lacks that specific information.

### Prompt injection prevention

The user's question is passed as a separate `user` message, never interpolated into
the system prompt. The context chunks come from Qdrant (trusted source), not from
user input.

```python
# Safe: user input is structurally isolated
messages = [LLMMessage(role="user", content=sanitize(question))]
system   = build_system_prompt(context_chunks)  # no user input here
```

```python
def sanitize(text: str) -> str:
    # Strip control characters that could affect prompt parsing
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', text)
    return cleaned[:1000]  # enforce max length at the Python level too
```

---

## Layer 3 — Output validation

**Enforced by:** `backend/app/api/v1/rag.py`

After the LLM responds, the output is validated before being returned to the client.

### JSON parsing with fallback

```python
def parse_llm_output(raw: str, chunks: list[SearchResult]) -> tuple[str, list[int]]:
    try:
        data = json.loads(raw.strip())
        answer = str(data["answer"])
        indices = [int(i) for i in data.get("cited_indices", [])]
        return answer, indices
    except Exception:
        # Fallback: use full response as answer, conservatively cite all chunks
        return raw.strip(), list(range(1, len(chunks) + 1))
```

### Answer length guard

```python
MAX_ANSWER_LENGTH = 3000  # characters

if len(answer) > MAX_ANSWER_LENGTH:
    answer = answer[:MAX_ANSWER_LENGTH] + "... [truncated]"
```

### Cited index bounds check

```python
valid_indices = [i for i in cited_indices if 1 <= i <= len(chunks)]
```

Indices outside the valid range are silently dropped rather than raising an error.
This prevents an LLM hallucination of `[6]` (when only 5 chunks exist) from crashing
the response.

---

## Guardrail decision matrix

| Input | Layer triggered | LLM called? | Response |
|-------|----------------|-------------|----------|
| Question < 3 chars | Layer 0 | No | HTTP 422 |
| Question > 1000 chars | Layer 0 | No | HTTP 422 |
| Over rate limit | Layer 1 | No | HTTP 429 |
| Off-topic, score < 0.35 | Layer 2a | No | `in_scope: false` |
| Borderline, LLM rejects | Layer 2b | Yes | `in_scope: true` but refusal answer |
| Knowledge gap (in-scope topic not in docs) | Layer 2b | Yes | "I don't have info about that" |
| Malformed LLM JSON | Layer 3 | Yes (already called) | Fallback parse, all chunks cited |
| LLM answer too long | Layer 3 | Yes (already called) | Truncated at 3000 chars |
| Normal in-scope question | None triggered | Yes | Full answer with sources |

---

## What guardrails do NOT cover (out of scope for v1.0)

| Risk | Why deferred |
|------|-------------|
| Medical advice detection | Needs a dedicated classifier; low risk given corpus |
| Personally identifiable information in questions | No PII expected in fitness questions; covered by general logging policy |
| Adversarial context injection via knowledge-base docs | Docs are internal, curated, and read-only |
| Toxicity / harmful content in answers | Anthropic's built-in safety filters cover this |

These will be reconsidered in v1.1 if usage data shows a need.
