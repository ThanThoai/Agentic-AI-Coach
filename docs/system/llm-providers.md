# LLM Providers

**Last updated:** 2026-05-12

## Supported Providers

| Provider | Class | Auth | Chat | Embed | Notes |
|---|---|---|---|---|---|
| Anthropic | `AnthropicProvider` | `ANTHROPIC_API_KEY` | ✅ | ❌ | Prompt caching enabled |
| OpenAI | `OpenAIProvider` | `OPENAI_API_KEY` | ✅ | ✅ | Default embeddings provider |
| Gemini | `GeminiProvider` | `GEMINI_API_KEY` | ✅ | ✅ | Uses `google-generativeai` SDK |
| Grok (xAI) | `GrokProvider` | `GROK_API_KEY` | ✅ | ❌ | OpenAI-compat at `api.x.ai/v1` |
| OpenRouter | `OpenRouterProvider` | `OPENROUTER_API_KEY` | ✅ | ✅* | Routes to 100+ models |

*OpenRouter embeddings are routed to OpenAI under the hood.

## Interface

All providers implement `BaseLLMProvider` in `app/llm/base.py`:

```python
async def complete(messages, *, model, max_tokens, temperature, system) -> LLMResponse
async def stream(messages, ...) -> AsyncIterator[str]
async def embed(texts, *, model) -> list[list[float]]
```

## Selecting a Provider

Set in `.env`:

```bash
DEFAULT_LLM_PROVIDER=anthropic     # for chat completions
DEFAULT_EMBEDDING_PROVIDER=openai  # for vector embeddings
```

Or select per-request in code:

```python
from app.llm.factory import get_step_provider
from app.core.config import LLMProvider, settings

provider = get_step_provider(LLMProvider.GEMINI, settings)
response = await provider.complete(messages)
```

For pipeline steps with per-step routing (RAG classifier, rewriter, generator, etc.), use `get_step_provider(cfg.rag_classifier_provider, cfg)` — it falls back to `default_llm_provider` when the step-specific override is `None`.

## Prompt Caching (Anthropic)

The `AnthropicProvider` automatically applies `cache_control: ephemeral` to the system prompt, activating Anthropic's prompt caching for repeated coaching queries that share the same system + knowledge context.

Log `cache_read_tokens > 0` to confirm cache hits.

## Model Recommendations

| Use case | Recommended | Reason |
|---|---|---|
| Production coaching | `claude-sonnet-4-6` | Best reasoning + caching |
| High-volume analysis | `claude-haiku-4-5-20251001` | Fastest, cheapest Anthropic |
| Embeddings | `text-embedding-3-small` | 1536 dims, cost-effective |
| Fallback / routing | OpenRouter `anthropic/claude-3.5-sonnet` | Provider resilience |
| Live tests | cheapest per provider | Minimise test cost |

## Adding a New Provider

1. Create `backend/app/llm/{provider_name}.py` extending `BaseLLMProvider`
2. Add the enum value to `LLMProvider` in `app/core/config.py`
3. Add config fields (`{PROVIDER}_API_KEY`, `{PROVIDER}_DEFAULT_MODEL`) to `Settings`
4. Register in `build_provider()` factory in `app/llm/factory.py`
5. Add mock test in `tests/mock/test_llm_providers.py`
6. Add live test fixture in `tests/live/conftest.py` + test in `tests/live/test_llm_providers.py`
