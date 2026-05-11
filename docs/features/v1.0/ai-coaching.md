# AI Coaching Chat

**Version:** v1.0 | **Status:** Specced | **Last updated:** 2026-05-11

## Problem

Users need personalised fitness advice grounded in their own workout history and evidence-based fitness knowledge.

## User stories

- As a user, I can ask the AI coach questions in natural language.
- As a user, coaching responses are personalised using my last 90 days of workouts.
- As a user, the response streams progressively (not wait for full reply).
- As a user, the coach cites which knowledge base articles informed its response.

## Architecture

```
User question
     │
     ▼ 1. Embed question → search knowledge_base (Qdrant, top-5 chunks)
     ▼ 2. Fetch last 90 days workout sets (PostgreSQL, most recent 200 sets)
     ▼ 3. Build prompt (system + knowledge context + workout history + question)
     ▼ 4. Stream response via SSE from LLM provider
     ▼ 5. Return citations (source_file list) alongside streamed text
```

## Prompt structure

```
[SYSTEM]
You are an expert fitness coach. Use the knowledge articles and the user's
workout history below to give personalised, evidence-based advice.
Always cite the article title when referencing a specific fact.

[KNOWLEDGE CONTEXT — injected from Qdrant results]
--- Bench Press Form ---
...

[WORKOUT HISTORY — injected from PostgreSQL]
Last 90 days: 47 sessions
Bench Press: 70 kg → 80 kg (+14.3%)
...

[USER QUESTION]
{question}
```

## API

```
POST /api/v1/coaching/chat          Returns SSE stream
Body: { "question": "string", "session_id": "uuid | null" }

SSE events:
  data: {"type": "delta", "text": "..."}
  data: {"type": "citations", "sources": ["01-bench-press.md"]}
  data: {"type": "done", "usage": {"total_tokens": 412}}
```

## Constraints

- Max question length: 1000 chars
- Coaching rate limit: 10 req/min per user
- LLM timeout: 30s (SSE connection drops with error event on timeout)
- Prompt caching: system + knowledge context cached for 5 min (Anthropic)
- No conversation history stored server-side in v1.0 (stateless per request)
