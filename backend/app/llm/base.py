from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str   # "system" | "user" | "assistant"
    content: str


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0      # populated by providers that support prompt caching


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: TokenUsage


class BaseLLMProvider(ABC):
    """Common interface for all LLM providers."""

    provider_name: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> LLMResponse:
        """Single-turn completion. Returns the full response once done."""

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream text chunks. Yields string deltas as they arrive."""

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Return embedding vectors for a list of texts."""
