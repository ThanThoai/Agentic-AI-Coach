from typing import AsyncIterator

from app.llm.base import LLMMessage, LLMResponse
from app.llm.openai import OpenAIProvider


class GrokProvider(OpenAIProvider):
    """xAI Grok — uses OpenAI-compatible API at https://api.x.ai/v1."""

    provider_name = "grok"

    def __init__(
        self,
        api_key: str,
        default_model: str = "grok-beta",
        base_url: str = "https://api.x.ai/v1",
    ) -> None:
        super().__init__(api_key=api_key, default_model=default_model, base_url=base_url)

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        # Grok does not yet expose an embeddings endpoint
        raise NotImplementedError(
            "Grok does not provide an embeddings API. "
            "Use DEFAULT_EMBEDDING_PROVIDER=openai or gemini."
        )
