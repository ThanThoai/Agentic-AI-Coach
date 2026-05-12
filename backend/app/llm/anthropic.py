from typing import AsyncIterator

import anthropic

from app.llm.base import (
    AgentLLMResponse,
    BaseLLMProvider,
    ContentBlock,
    LLMMessage,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


class AnthropicProvider(BaseLLMProvider):
    provider_name = "anthropic"

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model

    def _build_messages(self, messages: list[LLMMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

    def _extract_system(self, messages: list[LLMMessage], system: str | None) -> str | None:
        if system:
            return system
        for m in messages:
            if m.role == "system":
                return m.content
        return None

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> LLMResponse:
        system_prompt = self._extract_system(messages, system)
        kwargs: dict = dict(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._build_messages(messages),
        )
        if system_prompt:
            # Enable prompt caching on the system prompt for Anthropic
            kwargs["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]

        resp = await self._client.messages.create(**kwargs)
        usage = resp.usage
        return LLMResponse(
            content=resp.content[0].text,
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
        )

    async def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> LLMResponse:
        """Prefill the assistant turn with '{' so the model is forced to emit JSON."""
        system_prompt = self._extract_system(messages, system)
        api_messages = self._build_messages(messages)
        api_messages.append({"role": "assistant", "content": "{"})

        kwargs: dict = dict(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=api_messages,
        )
        if system_prompt:
            kwargs["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]

        resp = await self._client.messages.create(**kwargs)
        usage = resp.usage
        return LLMResponse(
            content="{" + resp.content[0].text,
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        system_prompt = self._extract_system(messages, system)
        kwargs: dict = dict(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._build_messages(messages),
        )
        if system_prompt:
            kwargs["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        # Anthropic does not offer an embeddings API — delegate to OpenAI or Gemini
        raise NotImplementedError(
            "Anthropic does not provide an embeddings API. "
            "Use DEFAULT_EMBEDDING_PROVIDER=openai or gemini."
        )

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
        kwargs: dict = dict(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
            tools=[
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ],
            tool_choice={"type": "auto"},
        )
        if system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]

        resp = await self._client.messages.create(**kwargs)

        blocks: list[ContentBlock] = []
        for block in resp.content:
            if block.type == "text":
                blocks.append(ContentBlock(type="text", text=block.text))
            elif block.type == "tool_use":
                blocks.append(
                    ContentBlock(
                        type="tool_use",
                        tool_call=ToolCall(id=block.id, name=block.name, input=block.input),
                    )
                )

        usage = resp.usage
        return AgentLLMResponse(
            stop_reason=resp.stop_reason or "end_turn",
            content_blocks=blocks,
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
        )
