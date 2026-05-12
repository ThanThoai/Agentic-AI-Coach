from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str   # "system" | "user" | "assistant"
    content: str


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0      # populated by providers that support prompt caching

    def __iadd__(self, other: "TokenUsage") -> "TokenUsage":
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.cache_read_tokens += other.cache_read_tokens
        return self


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: TokenUsage


# ── Tool-use types (agent loop) ────────────────────────────────────────────────

class ToolDefinition(BaseModel):
    """JSON Schema definition passed to the LLM to describe a callable tool."""
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM."""
    id: str
    name: str
    input: dict[str, Any]


class ContentBlock(BaseModel):
    """One block in an assistant turn — either text or a tool call."""
    type: str                   # "text" | "tool_use"
    text: str | None = None     # populated when type == "text"
    tool_call: ToolCall | None = None   # populated when type == "tool_use"


class AgentLLMResponse(BaseModel):
    """Response from complete_with_tools(), including stop reason."""
    stop_reason: str            # "end_turn" | "tool_use" | "max_tokens"
    content_blocks: list[ContentBlock]
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

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[ToolDefinition],
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> AgentLLMResponse:
        """Tool-use completion for the agent loop. Raw dicts for messages (supports
        tool_use / tool_result content blocks). Default implementation raises; providers
        that support tool use must override."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement complete_with_tools(). "
            "Use AnthropicProvider for agent tool-use."
        )
