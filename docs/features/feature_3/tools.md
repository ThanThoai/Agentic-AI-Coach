# Tools

**Component of:** Feature 3 — Coach Assist Agent
**Last updated:** 2026-05-12

---

## Responsibility

This layer defines the two tools the agent can call, how they are described to
Claude (JSON Schema), how they execute internally, and how their outputs are
formatted before being injected back into the conversation.

The LLM never calls HTTP endpoints — both tools are **direct Python function
calls** to the internal service layer. This avoids network overhead, double
authentication, and serialisation round-trips.

---

## Tool registry

```python
# app/agent/tools.py

TOOL_REGISTRY: dict[str, Callable] = {
    "rag_search":       tool_rag_search,
    "analyze_history":  tool_analyze_history,
}
```

The agent loop resolves a tool call by looking up `tool_call.name` in this dict.
An unrecognised name returns an error string without crashing the loop.

---

## Tool 1 — `rag_search`

### Purpose

Search the fitness knowledge base and return relevant information from the
curated document set. This tool answers **general fitness questions** that do
not require the user's personal workout data.

### JSON Schema for Claude

```json
{
  "name": "rag_search",
  "description": "Search the fitness knowledge base for general training, nutrition, and programming information. Use this when the question asks about principles, techniques, or general advice that doesn't depend on the user's specific workout history.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "A focused search query. Rephrase the user's question as a targeted knowledge lookup. Examples: 'progressive overload principles for intermediate lifters', 'RPE scale usage in strength training', 'shoulder impingement prevention exercises'.",
        "minLength": 3,
        "maxLength": 300
      }
    },
    "required": ["query"]
  }
}
```

### Execution

```python
async def tool_rag_search(query: str) -> str:
    # Calls Feature 1 pipeline internals directly — no HTTP
    from app.rag.guardrails import hard_block_check
    from app.rag.retriever import parallel_hybrid_search, assemble_context
    from app.rag.query_processor import process_query

    # Bypass guardrail Layer 1+2 — agent already validated the question
    processed = await process_query(query)
    results_per_query, merged = await parallel_hybrid_search(processed.sub_questions)
    context, assembled = assemble_context(merged, results_per_query, processed.query_type)

    if not assembled:
        return "NO_RESULTS: The knowledge base does not contain relevant information for this query."

    return _format_rag_result(assembled, context)
```

### Result format injected into messages

```
=== KNOWLEDGE BASE ===
Query: "progressive overload principles intermediate lifter"

[1] Progressive Overload — Core Principles (07-progressive-overload.md)
    For intermediate lifters, weight increments of 2.5 kg per session are
    recommended once all target reps are completed at RPE ≤ 8...

[2] Periodisation for Strength (12-periodisation.md)
    A linear progression model works for beginners; intermediates benefit
    from weekly undulation where intensity varies across sessions...

[3] Deload Weeks and Recovery (15-recovery.md)
    A planned deload every 4–8 weeks reduces accumulated fatigue and
    allows for supercompensation...
```

### Insufficient data behaviour

When `assembled` is empty (no chunks above the relevance threshold), the tool
returns `"NO_RESULTS: ..."`. The LLM can then tell the user that the knowledge
base does not cover this topic, rather than hallucinating an answer.

---

## Tool 2 — `analyze_history`

### Purpose

Analyse the authenticated user's personal workout history and return computed
metrics. This tool answers questions about **the user's own training data** —
trends, volume, muscle balance, readiness, and deload detection.

### JSON Schema for Claude

```json
{
  "name": "analyze_history",
  "description": "Analyse the user's personal workout history to answer questions about their training trends, exercise progression, muscle balance, deload weeks, or readiness to progress. Use this when the question is about the user's own data, not general fitness knowledge.",
  "input_schema": {
    "type": "object",
    "properties": {
      "question": {
        "type": "string",
        "description": "The specific analytical question to answer from the workout data. Be precise — for example: 'bench press weight trend over last 4 weeks', 'push/pull volume ratio this month', 'muscles not trained in the last 14 days'.",
        "minLength": 5,
        "maxLength": 500
      },
      "date_from": {
        "type": "string",
        "format": "date",
        "description": "Start of analysis window (ISO-8601 date). Defaults to 90 days ago if omitted."
      },
      "date_to": {
        "type": "string",
        "format": "date",
        "description": "End of analysis window (ISO-8601 date). Defaults to today if omitted."
      }
    },
    "required": ["question"]
  }
}
```

### user_id binding — isolation guarantee

The `user_id` is **never part of the tool input**. It is bound server-side
from the authenticated JWT before the loop starts and passed as a closed-over
variable into the tool wrapper:

```python
async def tool_analyze_history(
    question: str,
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    user_id: UUID,          # injected by the agent, not the LLM
) -> str:
    ...
```

The dispatch function closes over `user_id`:

```python
async def dispatch_tool(tool_call: ToolCall, user_id: UUID) -> str:
    fn = TOOL_REGISTRY[tool_call.name]
    return await fn(**tool_call.input, user_id=user_id)
```

This ensures the LLM cannot forge or alter the user identity even if it
attempts to inject `user_id` into the tool input — it is not in the schema
and would be rejected by the wrapper.

### Execution

```python
async def tool_analyze_history(
    question: str,
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    user_id: UUID,
) -> str:
    from app.services.workout import WorkoutService
    from app.schemas.workout import WorkoutAnalysisRequest

    request = WorkoutAnalysisRequest(
        question=question,
        date_from=date_from,
        date_to=date_to,
    )
    response = await WorkoutService(repo, providers).analyse(user_id, request)
    return _format_analysis_result(response)
```

### Result format injected into messages

```
=== WORKOUT ANALYSIS ===
Period: 2026-04-12 → 2026-05-12  |  Sessions: 14  |  Exercises: 7

BENCH PRESS
  Trend: 80.0 kg → 87.5 kg  (+9.4% over 4 weeks)
  Best set: 5 × 87.5 kg (2026-05-09)
  Avg volume/session: 1 155 kg  (sets × reps × weight)
  Consistency: 8/8 push sessions — no missed sessions

PUSH / PULL BALANCE
  Push volume: 18 450 kg  |  Pull volume: 15 200 kg
  Ratio: 1.21 : 1  (slightly push-dominant; target ≤ 1.2 : 1)

NEGLECTED MUSCLES
  None — all tracked groups trained within 7 days

DELOAD WEEKS
  None detected in the selected period
```

### Insufficient data behaviour

When the user has fewer than 2 sessions in the requested window, `WorkoutService`
returns `insufficient_data=True`. The tool formats this as:

```
=== WORKOUT ANALYSIS ===
INSUFFICIENT DATA: Only 0 sessions found in 2026-04-12 → 2026-05-12.
Log at least 2 sessions before requesting an analysis.
```

The LLM can then acknowledge the missing data and still answer the general
fitness question via `rag_search`.

---

## Tool result size limit

Long analytics blocks or large RAG contexts can push the total context window
past the model's practical limit across multiple loop iterations. Each tool
result is trimmed at the wrapper level:

```python
MAX_TOOL_RESULT_CHARS = 4_000

def _trim(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n[... result trimmed to 4 000 chars]"
```

This keeps each tool result under ~1k tokens, leaving headroom for the LLM's
reasoning and final answer within a 16k context window.
