# Agent Loop

**Component of:** Feature 3 — Coach Assist Agent
**Last updated:** 2026-05-12

---

## Responsibility

The agent loop is the control structure that drives multi-turn reasoning.
It sends the user's question to Claude, receives tool call requests, executes
the tools, feeds the results back, and repeats until Claude produces a final
text answer with no further tool calls.

The loop is entirely **server-side** — the client sends one request and receives
one response. The multi-turn reasoning is hidden inside `AgentService.run()`.

---

## Claude native tool_use protocol

Claude's tool_use feature works through the standard `messages` array. The
conversation alternates between `user` and `assistant` turns, with tool calls
and results embedded as typed content blocks.

### Content block types

| Block type | Who produces it | What it contains |
|------------|----------------|-----------------|
| `text` | Assistant | Reasoning text or final answer |
| `tool_use` | Assistant | Tool name + input parameters (JSON) |
| `tool_result` | User (injected by server) | Tool output string, keyed by `tool_use_id` |

### Example conversation structure

```
messages = [
  {
    "role": "user",
    "content": "Is my bench press ready to go heavier? What is progressive overload?"
  },

  # ── Turn 1: LLM requests two tools ────────────────────────────────────────
  {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "I'll check your workout history and look up progressive overload principles."
      },
      {
        "type": "tool_use",
        "id": "tu_01",
        "name": "analyze_history",
        "input": { "question": "bench press progression and readiness for weight increase" }
      },
      {
        "type": "tool_use",
        "id": "tu_02",
        "name": "rag_search",
        "input": { "query": "progressive overload principles intermediate lifter" }
      }
    ]
  },

  # ── Tool results injected by server ───────────────────────────────────────
  {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "tu_01",
        "content": "=== WORKOUT ANALYSIS ===\nBench Press: 80 kg → 87.5 kg over 4 weeks (+9.4%)..."
      },
      {
        "type": "tool_result",
        "tool_use_id": "tu_02",
        "content": "=== KNOWLEDGE BASE ===\n[1] Progressive Overload Guide — ...\n..."
      }
    ]
  },

  # ── Turn 2: LLM produces final answer ─────────────────────────────────────
  {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "Your bench press has progressed strongly (+9.4%) over 4 weeks..."
      }
    ]
  }
]
```

---

## Loop pseudocode

```python
async def run(question: str, user_id: UUID) -> AgentResponse:
    messages = [{"role": "user", "content": question}]
    tools_used: list[str] = []
    total_usage = Usage(prompt_tokens=0, completion_tokens=0)

    for iteration in range(MAX_ITERATIONS):          # MAX_ITERATIONS = 4
        response = await llm.complete(
            messages=messages,
            system=COACH_AGENT_SYSTEM,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=1024,
            temperature=0.3,
        )

        total_usage += response.usage
        messages.append({"role": "assistant", "content": response.content_blocks})

        if response.stop_reason == "end_turn":
            # LLM is done — extract final text answer
            answer = extract_text(response.content_blocks)
            return AgentResponse(answer=answer, tools_used=tools_used, ...)

        if response.stop_reason == "tool_use":
            tool_calls = extract_tool_calls(response.content_blocks)

            # Execute tool calls (possibly in parallel)
            results = await execute_tools(tool_calls, user_id)
            tools_used.extend(name for name, _ in results)

            # Inject tool results as next user turn
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": result}
                    for tc, result in zip(tool_calls, results)
                ]
            })

    # Safety: max iterations reached — return last text content or error
    raise AgentError("max_iterations_exceeded")
```

---

## Stopping conditions

| Condition | When it occurs | Action |
|-----------|---------------|--------|
| `stop_reason == "end_turn"` | LLM produced a text answer with no tool calls | Exit loop, return the text |
| `stop_reason == "tool_use"` | LLM requested ≥ 1 tools | Execute tools, inject results, continue |
| `iteration == MAX_ITERATIONS` | Loop guard triggered | Raise `AgentError`; return 500 to client |
| Tool execution exception | A tool call fails with an unhandled error | Inject error string as `tool_result`; LLM decides how to proceed |

---

## Parallel tool calls

Claude may return multiple `tool_use` blocks in a single assistant turn. When
this happens, the tools are executed concurrently with `asyncio.gather`:

```python
async def execute_tools(
    tool_calls: list[ToolCall],
    user_id: UUID,
) -> list[tuple[str, str]]:
    tasks = [dispatch_tool(tc, user_id) for tc in tool_calls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        (tc.name, format_result(r) if not isinstance(r, Exception) else format_error(r))
        for tc, r in zip(tool_calls, results)
    ]
```

This means a question like "Is my bench press ready and what is progressive
overload?" may complete in a single iteration (one parallel tool call turn +
one final answer turn), keeping total latency close to a single-tool scenario.

---

## Max iterations rationale

```
Simple question (one tool needed):
  iter 1: LLM → tool_use(rag_search) → result injected
  iter 2: LLM → end_turn → answer
  Total: 2 iterations

Complex question (both tools, sequential):
  iter 1: LLM → tool_use(analyze_history) → result injected
  iter 2: LLM → tool_use(rag_search) → result injected
  iter 3: LLM → end_turn → answer
  Total: 3 iterations

Complex question (both tools, parallel):
  iter 1: LLM → tool_use(analyze_history) + tool_use(rag_search) → both results injected
  iter 2: LLM → end_turn → answer
  Total: 2 iterations

MAX_ITERATIONS = 4 provides one extra iteration as safety margin.
```

---

## Aggregate token usage

Each LLM call in the loop produces its own `usage` object. The response returns
the **sum** across all turns:

```python
total_usage.prompt_tokens    += turn.usage.prompt_tokens
total_usage.completion_tokens += turn.usage.completion_tokens
```

This gives the client full cost visibility. Note that prompt tokens grow with
each iteration as tool results are appended to the context — the first turn is
the cheapest, subsequent turns are more expensive.

---

## Error handling in the loop

| Error type | Strategy |
|------------|----------|
| Tool function raises | Catch, format as `"ERROR: <message>"`, inject as `tool_result`, continue loop — LLM can reason about the failure |
| LLM call raises | Propagate as 500; no partial state to recover |
| `stop_reason == "max_tokens"` | Treat as `end_turn`; the partial answer is usable; log a warning |
| Iteration ceiling hit | Raise `AgentError("max_iterations_exceeded")`; return 500 |
