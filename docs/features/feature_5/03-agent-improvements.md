# Improvement 3 — Agent Improvements

## Problem

**Agent category pass rate: 60% (3/5).** Two failures:

### Failure A — agent-01: Tool timeout

**Query:** "Based on Binh's recent bench press history, is he ready to increase weight? What does proper progressive overload look like?"  
**Expected:** Combined answer using workout DB data + RAG knowledge base  
**Actual:** `runner_error: AgentError: tool_timeout` — empty answer, 0 ms latency recorded

**Root cause:** The agent's tool execution timeout (`agent_tool_timeout=45s`) was exceeded during a database tool call. The query requires a filtered time-series query on workout records. Under concurrent evaluation load, database or network latency pushed the tool call past the 45-second limit. The timeout is uniform across all tool types — a simple key-value lookup and an aggregation query share the same 45-second budget, which is too tight for the latter.

**Consequence:** The agent returned nothing rather than a partial or degraded answer. There is no retry — a single timeout causes total failure.

---

### Failure B — agent-03: Wrong date resolution

**Query:** "How has Alex's squat progressed this month?"  
**Expected:** Squat progress for May 2026  
**Actual:** Date range resolved to January 2025 (training-data era). The tool was called with `start_date=2025-01-01, end_date=2025-01-31`. The answer was disputed (Anthropic 4/5, OpenAI 2/5, Gemini 5/5, confidence 0.00).

**Root cause:** The agent system prompt and tool context do not inject the current date. When the agent sees "this month", it resolves the relative term against its training-data knowledge of "now", which produces a stale date. The model has no signal that it is running in May 2026.

**Safety / correctness consequence:** Any query with relative time references ("this week", "last month", "recently", "in the past 3 months") will silently return data from the wrong period. The agent will not flag the date mismatch — it confidently answers about the wrong timeframe.

---

## Changes

### Change 3A — Inject Current Date into Agent System Prompt (immediate, hours)

**File:** `app/prompts/agent.py` (agent system prompt definition)

Add a dynamic date injection at the top of the system prompt, immediately after the role description:

```python
from datetime import date

def build_agent_system_prompt() -> str:
    today = date.today().isoformat()   # e.g. "2026-05-12"
    return f"""
You are a strength and conditioning coach assistant with access to athlete workout data and a fitness knowledge base.

CURRENT DATE: {today}
When the user refers to "this week", "this month", "last week", "recently", or any other relative time
expression, resolve it against {today}. Always confirm the date range in your answer.

...
"""
```

**Resolution rules** to embed in the prompt:

| Phrase | Resolution |
|--------|-----------|
| "this month" | `[first day of current month, today]` |
| "last month" | `[first day of previous month, last day of previous month]` |
| "this week" | `[Monday of current week, today]` |
| "last week" | `[Monday of previous week, Sunday of previous week]` |
| "recently" / "recent" | `[today − 14 days, today]` |
| "past N days/weeks/months" | `[today − N×unit, today]` |

**Expected effect:** agent-03 resolves `start_date=2026-05-01, end_date=2026-05-12` instead of January 2025. Disputed helpfulness verdict becomes undisputed.

---

### Change 3B — Per-Tool-Type Timeout (immediate, days)

**File:** `app/agents/runner.py` (or wherever `agent_tool_timeout` is applied)

Replace the single global `agent_tool_timeout` with a per-category timeout map:

```python
TOOL_TIMEOUTS: dict[str, int] = {
    # Simple key-value lookups, single-row fetches
    "get_athlete_profile": 30,
    "get_workout_by_id": 30,

    # Aggregation / time-series queries — can be slow under concurrent load
    "get_workout_history": 90,
    "get_exercise_history": 90,
    "get_volume_summary": 90,
    "get_progress_metrics": 90,

    # LLM-backed tools (RAG, classifier) — bounded by LLM latency
    "rag_query": 60,
    "classify_intent": 60,

    # Default for any tool not explicitly listed
    "_default": 45,
}

def get_tool_timeout(tool_name: str) -> int:
    return TOOL_TIMEOUTS.get(tool_name, TOOL_TIMEOUTS["_default"])
```

Apply when dispatching a tool call:

```python
timeout = get_tool_timeout(tool_call.name)
result = await asyncio.wait_for(execute_tool(tool_call), timeout=timeout)
```

**Rationale:** The 45-second limit was designed for simple lookups. Aggregation queries on large workout histories legitimately need up to 90 seconds under eval-level concurrency. LLM-backed tools are bounded by the model provider's latency, not DB speed.

---

### Change 3C — Retry with Exponential Backoff for Tool Timeouts (days)

**File:** `app/agents/runner.py`

Wrap tool execution in a retry loop for tools that fail on transient network or DB conditions:

```python
RETRYABLE_TOOL_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError)
MAX_TOOL_RETRIES = 2

async def execute_tool_with_retry(tool_call: ToolCall) -> ToolResult:
    timeout = get_tool_timeout(tool_call.name)
    last_exc: Exception | None = None
    for attempt in range(1, MAX_TOOL_RETRIES + 1):
        try:
            return await asyncio.wait_for(execute_tool(tool_call), timeout=timeout)
        except RETRYABLE_TOOL_ERRORS as exc:
            last_exc = exc
            if attempt < MAX_TOOL_RETRIES:
                await asyncio.sleep(0.5 * 2 ** attempt)   # 1s, 2s
    raise AgentToolError(
        f"tool '{tool_call.name}' failed after {MAX_TOOL_RETRIES} attempts",
        tool_name=tool_call.name,
    ) from last_exc
```

**Scope:** Retry only on transient errors (`TimeoutError`, `ConnectionError`). Do not retry on semantic errors (e.g. athlete not found, invalid date range) — those are not transient and retrying is meaningless.

**Cap:** 2 retries maximum. A third timeout indicates a structural problem, not transient noise.

---

### Change 3D — Add agent-01 and agent-03 Variant Cases to Test Set (immediate)

Add the following cases to `tests/eval/dataset/agent_testset.json` to prevent regression:

| ID | Query | Expected | Failure mode tested |
|----|-------|----------|---------------------|
| agent-06 | "How has Alex's squat progressed this week?" | Answer with current-week date range | Date injection (relative: week) |
| agent-07 | "What did Binh train last month?" | Answer with previous calendar month | Date injection (relative: month) |

These complement the existing adv-02 regression tests added in `02-guardrail-hardening.md`.

---

## Acceptance Criteria

| Check | Target |
|-------|--------|
| agent-01 (bench timeout) | Completes within 90s, no `tool_timeout` error |
| agent-03 (squat this month) | Date range = May 2026, undisputed verdict |
| agent-06 (this week variant) | Correct date range resolved |
| agent-07 (last month variant) | Correct date range resolved |
| Agent category pass rate | ≥ 80% (4/5 original + 2 new = at least 4/7) |

---

## Files to Change

| File | Change |
|------|--------|
| `app/prompts/agent.py` | Inject `CURRENT DATE` + relative-term resolution table into system prompt |
| `app/agents/runner.py` | Replace `agent_tool_timeout` with `TOOL_TIMEOUTS` map; add retry loop |
| `tests/eval/dataset/agent_testset.json` | Add agent-06 and agent-07 |
| `tests/mock/test_agent.py` | Add unit tests for date injection and timeout retry logic |
