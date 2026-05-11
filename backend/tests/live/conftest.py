"""
Live test fixtures.
These tests call real external APIs — they only run when explicitly requested:

    uv run pytest -m live

Each provider fixture is skipped automatically if the corresponding API key is not set.
"""
import os
import pytest

from app.core.config import LLMProvider


def _require_key(env_var: str, provider: str):
    """Skip the test if the required env var is not set."""
    if not os.getenv(env_var):
        pytest.skip(f"{env_var} not set — skipping live {provider} test")


# ── Provider fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def live_anthropic():
    _require_key("ANTHROPIC_API_KEY", "Anthropic")
    from app.llm.anthropic import AnthropicProvider
    return AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        default_model=os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-4-5-20251001"),
    )


@pytest.fixture
def live_openai():
    _require_key("OPENAI_API_KEY", "OpenAI")
    from app.llm.openai import OpenAIProvider
    return OpenAIProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        default_model=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )


@pytest.fixture
def live_gemini():
    _require_key("GEMINI_API_KEY", "Gemini")
    from app.llm.gemini import GeminiProvider
    return GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        default_model=os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash"),
    )


@pytest.fixture
def live_grok():
    _require_key("GROK_API_KEY", "Grok")
    from app.llm.grok import GrokProvider
    return GrokProvider(
        api_key=os.environ["GROK_API_KEY"],
        default_model=os.getenv("GROK_DEFAULT_MODEL", "grok-beta"),
        base_url=os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"),
    )


@pytest.fixture
def live_openrouter():
    _require_key("OPENROUTER_API_KEY", "OpenRouter")
    from app.llm.openrouter import OpenRouterProvider
    return OpenRouterProvider(
        api_key=os.environ["OPENROUTER_API_KEY"],
        default_model=os.getenv("OPENROUTER_DEFAULT_MODEL", "anthropic/claude-3-haiku"),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        site_url=os.getenv("OPENROUTER_SITE_URL", "http://localhost:3000"),
        site_name=os.getenv("OPENROUTER_SITE_NAME", "CoachAgent"),
    )


@pytest.fixture
def live_qdrant():
    _require_key("QDRANT_URL", "Qdrant")
    from app.vectordb.qdrant import QdrantVectorDB
    return QdrantVectorDB.from_url(
        url=os.environ["QDRANT_URL"],
        collection_name="live_test_collection",
        api_key=os.getenv("QDRANT_API_KEY"),
    )
