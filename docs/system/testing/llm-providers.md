# LLM Providers: Test Scenarios

**Modules:** `app/llm/anthropic.py`, `app/llm/openai.py`, `app/llm/grok.py`,
`app/llm/openrouter.py`, `app/llm/factory.py`
**Test files:** `backend/tests/mock/test_llm_providers.py`, `backend/tests/live/test_llm_providers.py`
**Last updated:** 2026-05-11

---

## Overview

LLM provider tests verify two core behaviours:

1. **Request/response mapping** — the provider correctly translates `LLMMessage + system`
   into the HTTP body expected by each API, and parses the response into
   `LLMResponse(content, model, provider, usage)`.
2. **Embeddings** — the provider calls the correct embedding endpoint and returns
   `list[list[float]]`.

Mock tests use `respx` to intercept all HTTP traffic — no API keys required.
Live tests call real APIs using the cheapest available models.

---

## Mock tests — `tests/mock/test_llm_providers.py`

All tests use `@respx.mock` to intercept HTTP calls.

### Anthropic — `test_anthropic_complete`

**Setup:** Mock `POST https://api.anthropic.com/v1/messages` returning a standard response
with `content[0].text`.

| Assertion | Expected |
|-----------|----------|
| `resp.content.lower()` | Contains `"progressive overload"` |
| `resp.provider` | `"anthropic"` |
| `resp.usage.total_tokens` | `input_tokens + output_tokens = 15 + 12 = 27` |

**Key point:** Anthropic returns usage as `input_tokens` / `output_tokens` (not
`prompt_tokens` / `completion_tokens` like OpenAI). The provider must map both
field names correctly into `TokenUsage`.

---

### OpenAI complete — `test_openai_complete`

**Setup:** Mock `POST https://api.openai.com/v1/chat/completions`.

| Assertion | Expected |
|-----------|----------|
| `resp.content` | `"Progressive overload is key."` (exact match) |
| `resp.provider` | `"openai"` |
| `resp.usage.total_tokens` | `22` |

---

### OpenAI embeddings — `test_openai_embed`

**Setup:** Mock `POST https://api.openai.com/v1/embeddings` returning
`data[0].embedding = [0.1, 0.2, 0.3]`.

| Assertion | Expected |
|-----------|----------|
| `len(vectors)` | `1` |
| `len(vectors[0])` | `3` |

---

### Grok — `test_grok_complete`

**Setup:** Mock `POST https://api.x.ai/v1/chat/completions` (OpenAI-compatible endpoint).

| Assertion | Expected |
|-----------|----------|
| `resp.provider` | `"grok"` |
| `resp.usage.total_tokens` | `15` |

---

### OpenRouter — `test_openrouter_complete`

**Setup:** Mock `POST https://openrouter.ai/api/v1/chat/completions`.

| Assertion | Expected |
|-----------|----------|
| `resp.provider` | `"openrouter"` |
| `"consistency"` in `resp.content.lower()` | `True` |

---

### Factory — `test_factory_builds_correct_provider`

**Setup:** Instantiate `Settings` with `default_llm_provider=LLMProvider.ANTHROPIC`.

| Assertion | Expected |
|-----------|----------|
| `isinstance(provider, AnthropicProvider)` | `True` |

**Why this matters:** `build_provider()` is the single entry point for every LLM call in
the system. Returning the wrong subclass would silently break all downstream pipeline calls.

---

## Live tests — `tests/live/test_llm_providers.py`

> Run with: `uv run pytest -m live`
> Requirements: `.env.test` must contain real API keys. Each test skips automatically
> if the relevant key is absent.
> Uses the smallest available models and `max_tokens=16` to minimise cost.

### Anthropic

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_anthropic_live_complete` | Calls `complete()` with `max_tokens=16` | `resp.content` is non-empty; `usage.total_tokens > 0`; `provider == "anthropic"` |
| `test_anthropic_live_stream` | Calls `stream()`, collects all chunks | `len(chunks) > 0`; joined text is non-empty |

### OpenAI

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_openai_live_complete` | Calls `complete()` | `resp.content` is non-empty; `provider == "openai"` |
| `test_openai_live_embed` | Calls `embed(["bench press form", "squat depth"])` | `len(vectors) == 2`; `len(vectors[0]) > 100` (text-embedding-3-small = 1536 dims) |

### Gemini

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_gemini_live_complete` | Calls `complete()` | `resp.content` is non-empty; `provider == "gemini"` |
| `test_gemini_live_embed` | Calls `embed()` | `len(vectors[0]) > 100` |

### Grok and OpenRouter

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_grok_live_complete` | Calls `complete()` | `resp.content` is non-empty; `provider == "grok"` |
| `test_openrouter_live_complete` | Calls `complete()` | `resp.content` is non-empty; `provider == "openrouter"` |

### Qdrant live

| Test | Behaviour | Expected |
|------|-----------|----------|
| `test_qdrant_live_upsert_search` | Upsert 1 point, search, delete | `results[0].score > 0.9`; cleanup succeeds |

---

## Provider capability matrix

| Provider | `complete()` | `stream()` | `embed()` | Base URL |
|----------|:-----------:|:----------:|:---------:|----------|
| Anthropic | ✅ mock + live | ✅ live | — | `api.anthropic.com` |
| OpenAI | ✅ mock + live | — | ✅ mock + live | `api.openai.com` |
| Grok | ✅ mock + live | — | — | `api.x.ai` |
| OpenRouter | ✅ mock + live | — | — | `openrouter.ai` |
| Gemini | — | — | ✅ live | `generativelanguage.googleapis.com` |

---

## Running

```bash
# Mock tests only
uv run pytest tests/mock/test_llm_providers.py -v

# Live tests (requires API keys)
uv run pytest tests/live/test_llm_providers.py -v -m live

# Single provider
uv run pytest tests/mock/test_llm_providers.py::test_anthropic_complete -v
uv run pytest tests/live/test_llm_providers.py::test_anthropic_live_stream -v
```

---

## Adding a new provider

When adding a new provider (e.g. a Gemini mock test):

1. Add a mock test in `tests/mock/test_llm_providers.py`:
   ```python
   @pytest.mark.mock
   @respx.mock
   async def test_gemini_complete():
       respx.post("https://generativelanguage.googleapis.com/...").mock(...)
       provider = GeminiProvider(api_key="fake")
       resp = await provider.complete(MESSAGES)
       assert resp.provider == "gemini"
   ```

2. Add a live test in `tests/live/test_llm_providers.py` with `@pytest.mark.live`.

3. Update the capability matrix in this document.

---

## See also

- `docs/system/llm-providers.md` — provider architecture, configuration, prompt caching
- `docs/system/testing/README.md` — test tiers overview, `MockLLMProvider` usage
