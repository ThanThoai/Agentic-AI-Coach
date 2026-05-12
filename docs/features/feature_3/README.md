# Feature 3 — Coach Assist Agent

**Status:** Implemented | **Last updated:** 2026-05-12

---

## Requirement

> Build a simple agent that helps a coach answer a multi-step question by deciding
> which tools to use and in what order.
>
> The agent must have access to at least two tools:
> - `rag_search(query)` — Feature 1 RAG pipeline (fitness knowledge base)
> - `analyze_history(athlete, question)` — Feature 2 analysis for a named athlete
>
> The agent must:
> - Decide which tools to call and in what sequence — do not hardcode the call order
> - Produce a single coherent response that cites both data sources when both are used
> - Handle the case where one tool returns insufficient data gracefully

---

## Example questions

| Question | Expected tool usage |
|----------|-------------------|
| "Based on Binh's recent workout history, is his bench ready for a weight increase? What does progressive overload look like?" | `analyze_history(athlete="Binh", ...)` → `rag_search` |
| "Compare Alex and Binh's push/pull volume — who needs more pulling work?" | `analyze_history` × 2 (parallel) → `rag_search` |
| "What is RPE and how should I use it?" | `rag_search` only |
| "How has Alex's squat progressed this month?" | `analyze_history` only |
| "Should I deload Binh this week?" | `analyze_history` → `rag_search` |

---

## Component docs

| File | Scope |
|------|-------|
| [agent-loop.md](./agent-loop.md) | Claude native tool_use protocol, conversation structure, stopping conditions, max iterations, parallel tool calls, timeout/keepalive, error handling |
| [tools.md](./tools.md) | Tool definitions (JSON Schema), `rag_search` and `analyze_history` wrappers, roster resolution, result formatting, insufficient data handling |
| [synthesis.md](./synthesis.md) | Final response synthesis — system prompt, citation format, combining both data sources, tone and coherence |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONLINE — per coach request
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/agent/ask         ← single JSON response
  POST /api/v1/agent/ask/stream  ← SSE streaming
          │
          ▼  Auth middleware
    get_current_user()  →  user_id  (role must be "coach")
          │
          ▼  AgentService.run_stream(question, user_id)
    Build initial messages:
      [{ role: user, content: question }]
          │
          ▼ ── Agent loop (max 4 iterations) ────────────────────
          │
          │  LLM call  (Sonnet, tool_choice="auto", timeout 60 s)
          │  keepalive: ping SSE client every 5 s during LLM wait
          │       │
          │       ├─ stop_reason == "end_turn"
          │       │      → yield token event; yield done event; exit
          │       │
          │       └─ stop_reason == "tool_use"
          │              → yield status event  {tools: [{name, input}]}
          │              → execute tool(s) in parallel (asyncio.gather)
          │                keepalive: ping SSE client during tool wait
          │              → append tool_result blocks to messages
          │              → record {name, input, result_chars} per tool
          │              → next iteration
          │
          ├─ rag_search(query)
          │    └─ calls Feature 1 pipeline directly (no HTTP)
          │       → returns structured knowledge block
          │
          └─ analyze_history(athlete, question, date_from?, date_to?)
               └─ resolves athlete name → user_id via server-side roster
                  calls Feature 2 analytics + LLM directly
                  → returns structured analysis block
          │
          ▼ ── End loop ──────────────────────────────────────────
          │
          ▼  SSE events
    status  { type:"status", tools:[{name, input}] }     ← before each tool batch
    token   { type:"token",  content:"..." }              ← final answer text
    done    { type:"done",   answer, tools_used,
              tool_calls:[{name,input,result_chars}],
              iterations, usage }
    ping    { type:"ping" }                               ← keepalive (ignore)
    error   { type:"error", message:"..." }               ← on failure
```

---

## Key design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Tool selection | LLM decides via `tool_choice="auto"` | Satisfies "do not hardcode call order"; LLM reasons about which data is needed |
| Parallel tool calls | Supported — multiple `tool_use` blocks execute with `asyncio.gather` | Claude requests both tools in a single turn when needed; halves latency for dual-tool questions |
| Athlete resolution | Agent passes athlete *name*; server resolves name → user_id via `ATHLETE_ROSTER` | LLM cannot forge user identity; coach specifies athletes by name in natural language |
| Internal tool calls | Direct function calls, not HTTP | Avoids network overhead and double auth; Feature 1 and Feature 2 services are imported directly |
| Max iterations | 4 | Safety ceiling; simple questions need ≤ 2 iterations, complex ones ≤ 3 |
| Stop condition | `stop_reason == "end_turn"` | Claude's native signal that it has produced a final answer |
| Timeout + keepalive | LLM call: 60 s, tool call: 45 s; ping every 5 s | Prevents SSE connection timeout during long LLM/tool waits without dropping the stream |
| SSE streaming | `POST /api/v1/agent/ask/stream` | Lets the UI show tool usage steps and final answer without a long blocking wait |
| Insufficient data | Tool returns structured error string; LLM decides how to respond | Agent can still answer the knowledge part even if workout data is missing |
| Provider | Sonnet for orchestration | Needs strong reasoning to decide tool order and synthesise multi-source answers |

---

## File layout

```
backend/app/
├── agent/
│   ├── __init__.py
│   ├── service.py          AgentService.run() / run_stream() — the main agent loop
│   ├── tools.py            Tool wrappers: tool_rag_search(), tool_analyze_history()
│   ├── tool_schemas.py     JSON Schema definitions for Claude tool_use
│   └── roster.py           ATHLETE_ROSTER — name → user_id mapping
├── prompts/
│   └── agent.py            COACH_AGENT_SYSTEM prompt
├── schemas/
│   └── agent.py            AgentRequest, AgentResponse, AgentToolCall Pydantic schemas
└── api/v1/
    └── agent.py            POST /api/v1/agent/ask and /ask/stream route handlers

backend/tests/mock/
└── test_agent.py           Agent loop tests, tool routing tests, timeout fixture
```

---

## API contract

### Request (both endpoints)

```http
POST /api/v1/agent/ask
POST /api/v1/agent/ask/stream
Authorization: Bearer <token>   (role must be "coach")
Content-Type: application/json
```

```json
{
  "question": "Based on Binh's recent workout history, is he ready to increase bench press weight? What does proper progressive overload look like?"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | `string` | 5–1000 characters |

---

### Non-streaming response (`/ask`)

```json
{
  "answer": "Binh's bench press has progressed from 55 kg to 62.5 kg (+13.6%) over the last 6 weeks...",
  "tools_used": ["analyze_history", "rag_search"],
  "tool_calls": [
    {
      "name": "analyze_history",
      "input": { "athlete": "Binh", "question": "bench press trend and readiness for weight increase" },
      "result_chars": 1842
    },
    {
      "name": "rag_search",
      "input": { "query": "progressive overload principles intermediate lifter bench press" },
      "result_chars": 2150
    }
  ],
  "iterations": 2,
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
| `tools_used` | `string[]` | Names of tools called (may repeat if called multiple times) |
| `tool_calls` | `object[]` | Full detail per call: `name`, `input` params, `result_chars` |
| `iterations` | `integer` | Number of LLM turns in the loop |
| `usage` | `object` | Aggregate token usage across all LLM turns |

---

### Streaming events (`/ask/stream`)

The server sends `text/event-stream` with `data: <json>\n\n` lines.

| Event type | Payload | When |
|------------|---------|------|
| `status` | `{ tools: [{name, input}] }` | Before each tool batch executes |
| `token` | `{ content: "..." }` | Final answer text (sent once) |
| `done` | Full response object (same as non-streaming) | After answer |
| `ping` | `{}` | Every 5 s during long LLM/tool waits — ignore |
| `error` | `{ message: "..." }` | On timeout or unhandled error |

---

## Open questions

1. **Token budget across turns** — Each loop iteration consumes tokens. With 4 iterations × ~2k tokens, the total could reach 8k+ per request. Monitor usage and add a token budget guard if costs become a concern.
2. **Tool output size** — `analyze_history` can return a long analytics block. If the context grows too large, later LLM calls may degrade. The current 4 000-char trim is a heuristic; tune if needed.
3. **Agent evaluation** — Measuring whether the agent picked the right tools and produced a grounded answer is harder than measuring RAG recall. A test set of labelled (question → expected tools + key facts) pairs is needed before production.
4. **Roster expansion** — Adding a new athlete currently requires editing `app/agent/roster.py` and re-deploying. A DB-backed roster (coach–athlete relationship model) would be more flexible.
