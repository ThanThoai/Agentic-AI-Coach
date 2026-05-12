from functools import lru_cache

from app.core.config import LLMProvider, Settings, settings as _default_settings
from app.llm.base import BaseLLMProvider


def build_provider(provider: LLMProvider, cfg: Settings) -> BaseLLMProvider:
    """Instantiate the requested LLM provider using keys from config."""
    if provider == LLMProvider.ANTHROPIC:
        from app.llm.anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=cfg.get_api_key(provider),
            default_model=cfg.anthropic_default_model,
        )

    if provider == LLMProvider.OPENAI:
        from app.llm.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=cfg.get_api_key(provider),
            default_model=cfg.openai_default_model,
            embedding_model=cfg.openai_embedding_model,
        )

    if provider == LLMProvider.GEMINI:
        from app.llm.gemini import GeminiProvider
        return GeminiProvider(
            api_key=cfg.get_api_key(provider),
            default_model=cfg.gemini_default_model,
        )

    if provider == LLMProvider.GROK:
        from app.llm.grok import GrokProvider
        return GrokProvider(
            api_key=cfg.get_api_key(provider),
            default_model=cfg.grok_default_model,
            base_url=cfg.grok_base_url,
        )

    if provider == LLMProvider.OPENROUTER:
        from app.llm.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            api_key=cfg.get_api_key(provider),
            default_model=cfg.openrouter_default_model,
            base_url=cfg.openrouter_base_url,
            site_url=cfg.openrouter_site_url,
            site_name=cfg.openrouter_site_name,
        )

    raise ValueError(f"Unknown provider: {provider}")


@lru_cache
def get_default_llm(cfg: Settings = _default_settings) -> BaseLLMProvider:
    return build_provider(cfg.default_llm_provider, cfg)


@lru_cache
def get_default_embedder(cfg: Settings = _default_settings) -> BaseLLMProvider:
    return build_provider(cfg.default_embedding_provider, cfg)


# ── Per-step provider singletons ──────────────────────────────────────────────
# Steps sharing the same resolved provider reuse the same cached instance.

@lru_cache
def _cached_provider(provider: LLMProvider) -> BaseLLMProvider:
    return build_provider(provider, _default_settings)


def get_step_provider(
    step_provider: LLMProvider | None,
    cfg: Settings = _default_settings,
) -> BaseLLMProvider:
    """Return a cached provider for a pipeline step, falling back to default."""
    resolved = step_provider or cfg.default_llm_provider
    return _cached_provider(resolved)


class PipelineProviders:
    """All per-step providers resolved from config. Used as a FastAPI dependency.

    Model resolution priority (highest → lowest):
      1. RAG_<STEP>_MODEL env var (explicit override)
      2. openrouter_<step>_model defaults (when effective provider is OpenRouter)
      3. Provider's own default_model
    """

    def __init__(self, cfg: Settings = _default_settings) -> None:
        self.guardrail  = get_step_provider(cfg.rag_guardrail_provider,  cfg)
        self.classifier = get_step_provider(cfg.rag_classifier_provider, cfg)
        self.rewrite    = get_step_provider(cfg.rag_rewrite_provider,    cfg)
        self.conflict   = get_step_provider(cfg.rag_conflict_provider,   cfg)
        self.generation = get_step_provider(cfg.rag_generation_provider, cfg)
        self.embedder   = get_default_embedder()

        self.guardrail_model  = self._resolve_model(cfg.rag_guardrail_model,  cfg.rag_guardrail_provider,  cfg.openrouter_guardrail_model,  cfg)
        self.classifier_model = self._resolve_model(cfg.rag_classifier_model, cfg.rag_classifier_provider, cfg.openrouter_classifier_model, cfg)
        self.rewrite_model    = self._resolve_model(cfg.rag_rewrite_model,    cfg.rag_rewrite_provider,    cfg.openrouter_rewrite_model,    cfg)
        self.conflict_model   = self._resolve_model(cfg.rag_conflict_model,   cfg.rag_conflict_provider,   cfg.openrouter_conflict_model,   cfg)
        self.generation_model = self._resolve_model(cfg.rag_generation_model, cfg.rag_generation_provider, cfg.openrouter_generation_model, cfg)

    @staticmethod
    def _resolve_model(
        explicit: str | None,
        step_provider: LLMProvider | None,
        openrouter_default: str,
        cfg: Settings,
    ) -> str | None:
        if explicit:
            return explicit
        effective = step_provider or cfg.default_llm_provider
        if effective == LLMProvider.OPENROUTER:
            return openrouter_default
        return None
