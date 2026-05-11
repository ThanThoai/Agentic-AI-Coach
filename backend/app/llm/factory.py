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
