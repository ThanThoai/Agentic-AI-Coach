# Changelog

All notable changes to Coach Agent are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added — Feature 3: Coach Assist Agent
- `POST /api/v1/agent/ask` — ReAct agent loop (max 4 iterations)
- `POST /api/v1/agent/ask/stream` — SSE streaming variant
- Two tools: `rag_search` (Feature 1 pipeline) and `analyze_history` (Feature 2 analytics)
- Parallel tool execution via `asyncio.gather`
- Athlete name resolution server-side via `ATHLETE_ROSTER` (coach specifies by name)
- Timeout enforcement: 60 s LLM, 45 s tool; keepalive ping every 5 s over SSE
- `AgentResponse` includes `tool_calls` list with `name`, `input`, `result_chars` per call
- `status` SSE event carries full tool input params (not just names)
- `app/prompts/agent.py` — `COACH_AGENT_SYSTEM` consolidated into prompts package

### Added — Feature 2: Workout History Analysis
- `POST /api/v1/workout/log` — ingest flat exercise entries; normalise to kg; group by date
- `POST /api/v1/workout/analyze` — analytics + LLM analysis
- `POST /api/v1/workout/analyze/stream` — SSE streaming variant
- `question_type` classifier (TREND / BALANCE / NEGLECT / PLAN / GENERAL) + `focus` field
- Analytics engine: volume, trends, balance ratio, neglect check, deload detection
- `WorkoutAnalysisResponse` includes `question_type` and `focus`

### Added — Feature 1: Fitness Knowledge RAG
- Offline ingestion pipeline: parser → metadata → chunker → embedder → Qdrant upsert
- Hybrid search: dense (text-embedding-3-small, 1536 dim) + sparse (BM25 fastembed)
- Qdrant `Prefetch[top-20 dense, top-20 sparse]` + RRF fusion
- Query pipeline: classify (SIMPLE/COMPLEX/COMPARISON) → rewrite or decompose → parallel retrieval → context assembly
- Context strategies: aggregate / chain / compare; conflict detection (heuristic + optional LLM)
- 3-layer guardrails: regex rule filter, LLM intent classifier, output filter
- `POST /api/v1/rag/query` and `/query/stream` (SSE)

### Added — Infrastructure
- FastAPI backend with async SQLAlchemy, Alembic migrations, structlog
- Multi-provider LLM abstraction: Anthropic, OpenAI, Gemini, Grok, OpenRouter
- Per-step model routing for all pipelines (classifier, rewriter, generator, etc.)
- Next.js 14 App Router frontend: chat UI with three query modes, SSE streaming, trace sidebar
- Trace sidebar: per-tool call cards (inputs + result size), question type badge, RAG pipeline steps
- Unified chat UI for all user roles (badge + `/` slash command switcher)
- Docker Compose setup for local development (backend, frontend, Qdrant, PostgreSQL)
- Mock test suite (CI-safe, no API keys): 179 tests
- Live test suite (real providers, opt-in with `-m live`)

---

## [0.1.0] — 2026-05-11

### Added
- Initial repository setup
- `.claude/` project configuration with rules for FastAPI, Next.js, API design, database, logging, security
- Multi-provider LLM abstraction scaffolding
- Knowledge base documents (20 fitness topics)
- Sample workout history data for two users (Alex, Binh)
