# Feature 3 — Coach Assist Agent

**Version:** v1.0 | **Status:** Planned | **Last updated:** 2026-05-12

---

## Requirement

> Build a simple agent that helps a coach answer a multi-step question by deciding
> which tools to use and in what order.
>
> The agent must have access to at least two tools:
> - `rag_search(query)` — Feature 1 RAG pipeline (fitness knowledge base)
> - `analyze_history(question)` — Feature 2 analysis endpoint (user's workout data)
>
> The agent must:
> - Decide which tools to call and in what sequence — do not hardcode the call order
> - Produce a single coherent response that cites both data sources when both are used
> - Handle the case where one tool returns insufficient data gracefully

---

## Example questions

| Question | Expected tool usage |
|----------|-------------------|
| "Based on my recent workout history, is my bench press ready for a weight increase? What does proper progressive overload look like?" | `analyze_history` → `rag_search` |
| "I haven't done any pulling exercises this month and am getting shoulder tightness. What should I do?" | `analyze_history` (verify pulling deficit) → `rag_search` (shoulder health + pulling exercises) |
| "What is RPE and how should I use it?" | `rag_search` only |
| "How has my squat progressed?" | `analyze_history` only |
| "Should I deload this week?" | `analyze_history` (detect deload signals) → `rag_search` (deload principles) |

---

## Component docs

| File | Scope |
|------|-------|
| [agent-loop.md](./agent-loop.md) | Claude native tool_use protocol, conversation structure, stopping conditions, max iterations, parallel tool calls, error handling |
| [tools.md](./tools.md) | Tool definitions (JSON Schema), `rag_search` and `analyze_history` wrappers, result formatting, insufficient data handling |
| [synthesis.md](./synthesis.md) | Final response synthesis — system prompt, citation format, combining both data sources, tone and coherence |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONLINE — per coach request
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/agent/ask  { "question": "..." }
          │
          ▼  Auth middleware
    get_current_user()  →  user_id
    (bound to analyze_history tool — isolation guaranteed)
          │
          ▼  AgentService.run(question, user_id)
    Build initial messages:
      [system_prompt, { role: user, content: question }]
          │
          ▼ ── Agent loop (max 4 iterations) ───────────────────
          │
          │  LLM call  (Sonnet, tool_choice="auto")
          │       │
          │       ├─ stop_reason == "end_turn"
          │       │      → exit loop; final answer is text content
          │       │
          │       └─ stop_reason == "tool_use"
          │              → parse tool call(s) from content blocks
          │              → execute tool(s) — possibly in parallel
          │              → append tool_result blocks to messages
          │              → next iteration
          │
          ├─ rag_search(query)
          │    └─ calls Feature 1 pipeline internally (no HTTP)
          │       → formats result as structured text block
          │
          └─ analyze_history(question)
               └─ calls Feature 2 analytics + LLM internally
                  user_id injected from auth context (not from LLM)
                  → formats result as structured text block
          │
          ▼ ── End loop ───────────────────────────────────────
          │
          ▼  AgentResponse
    { answer, tools_used, model, usage }
```

---

## Key design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Tool selection | LLM decides via `tool_choice="auto"` | Satisfies the "do not hardcode call order" requirement; LLM reasons about which data is needed |
| Parallel tool calls | Supported — multiple tool_use blocks in one LLM turn execute with `asyncio.gather` | Claude may request both tools in a single turn when the question clearly needs both; reduces latency |
| user_id binding | Injected server-side from JWT, not passed by LLM | LLM cannot forge or alter the user identity; tool wrapper always uses the authenticated user |
| Internal tool calls | Direct function calls, not HTTP | Avoids network overhead and double auth; Feature 1 and Feature 2 services are imported directly |
| Max iterations | 4 | Prevents infinite loops; a simple question needs ≤ 2 iterations (one tool call + final answer), complex ones ≤ 3; 4 is a safety ceiling |
| Stop condition | `stop_reason == "end_turn"` | Claude's native signal that it is done reasoning and has produced a final answer |
| Insufficient data handling | Tool returns a structured error string; LLM decides how to respond | The agent can still answer the knowledge part even if workout data is missing — graceful degradation |
| Provider | Sonnet for orchestration | Needs strong reasoning to decide tool order and synthesize multi-source answers; Haiku is insufficient for this |
| No streaming | Single POST response | The agent loop makes multiple LLM calls; streaming mid-loop is complex and not required by the spec |

---

## File layout

```
backend/app/
├── agent/
│   ├── __init__.py
│   ├── service.py          AgentService.run() — the main agent loop
│   ├── tools.py            Tool wrappers: rag_search(), analyze_history()
│   ├── tool_schemas.py     JSON Schema definitions for Claude tool_use
│   └── prompts.py          COACH_AGENT_SYSTEM prompt
├── schemas/
│   └── agent.py            AgentRequest, AgentResponse Pydantic schemas
└── api/v1/
    └── agent.py            POST /api/v1/agent/ask route handler

backend/tests/mock/
└── test_agent.py           Agent loop tests, tool routing tests, isolation test
```

---

## API contract

### Request

```http
POST /api/v1/agent/ask
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "question": "Based on my recent workout history, is my bench press ready for a weight increase? What does progressive overload look like for my level?"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | `string` | 5–1000 characters |

### Response

```json
{
  "answer": "Looking at your bench press data over the past 4 weeks, you've progressed from 80 kg to 87.5 kg (+9.4%), completing all target reps without a missed set. This is a strong signal that you're ready for a small increase...\n\nAccording to progressive overload principles, for intermediate lifters the recommended increment is 2.5 kg per session once you can complete all sets at the target rep range with RPE ≤ 8 [1]...",
  "tools_used": ["analyze_history", "rag_search"],
  "model": "claude-sonnet-4-6",
  "usage": {
    "prompt_tokens": 1840,
    "completion_tokens": 420,
    "total_tokens": 2260
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `answer` | `string` | Markdown; cites workout numbers and knowledge sources |
| `tools_used` | `string[]` | Subset of `["rag_search", "analyze_history"]`; empty if answered directly |
| `model` | `string` | Model used for the final generation turn |
| `usage` | `object` | Aggregate across all LLM turns in the loop |

---

## Open questions

1. **Multi-client coach scenario** — The current design binds `analyze_history` to the authenticated user. A real coach may want to query a specific client's data. Future work: add `client_id` parameter and an explicit coach–client relationship model.
2. **Token budget across turns** — Each loop iteration consumes tokens. With 4 iterations × ~2k tokens, the total could reach 8k+ per request. Monitor usage and add a token budget guard if costs become a concern.
3. **Tool output size** — `analyze_history` can return a long analytics block. If the context grows too large, later LLM calls may degrade. Consider trimming tool results to a max character count before injecting.
4. **Caching** — If the user asks the same question twice, both tool calls will re-execute. Short-lived caching (TTL ~5 min) on `analyze_history` results (keyed by user_id + question hash) could reduce cost.
5. **Agent evaluation** — Measuring whether the agent picked the right tools and produced a grounded answer is harder than measuring RAG recall. A test set of labelled (question → expected tools + key facts) pairs is needed before production.
