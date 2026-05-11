# Changelog

All notable changes to Coach Agent are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- Project scaffolding: `backend/`, `frontend/`, `docs/` root folders
- Multi-provider LLM abstraction (Anthropic, OpenAI, Gemini, Grok, OpenRouter)
- Qdrant vector database client with async support
- Mock and live test environments
- `.claude/` rules and hooks for development guardrails

---

## [0.1.0] — 2026-05-11

### Added
- Initial repository setup
- `.claude/` project configuration with rules for FastAPI, Next.js, API design, database, logging, security
- Knowledge base documents (20 fitness topics)
- Sample workout history data for two users

[Unreleased]: https://github.com/your-org/coach-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/coach-agent/releases/tag/v0.1.0
