from app.llm.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter — routes to 100+ models via OpenAI-compatible API."""

    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        default_model: str = "anthropic/claude-3.5-sonnet",
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: str = "http://localhost:3000",
        site_name: str = "CoachAgent",
    ) -> None:
        # OpenRouter requires extra headers for attribution
        import httpx
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
        self._default_model = default_model
        self._embedding_model = "openai/text-embedding-3-small"
