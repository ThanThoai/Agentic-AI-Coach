import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

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


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-small",
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model
        self._embedding_model = embedding_model

    def _to_oai_messages(
        self, messages: list[LLMMessage], system: str | None
    ) -> list[dict]:
        result: list[dict] = []
        if system:
            result.append({"role": "system", "content": system})
        for m in messages:
            result.append({"role": m.role, "content": m.content})
        return result

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=self._to_oai_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
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
        resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=model or self._default_model,
            messages=self._to_oai_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
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
        async with await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=self._to_oai_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    async def embed(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        resp = await self._client.embeddings.create(
            model=model or self._embedding_model,
            input=texts,
        )
        return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> AgentLLMResponse:
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

        resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=model or self._default_model,
            messages=self._to_oai_agent_messages(messages, system),
            tools=oai_tools,
            tool_choice="auto",
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )

        choice = resp.choices[0]
        # "tool_calls" → our "tool_use"; "stop" → "end_turn"
        stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        blocks: list[ContentBlock] = []
        if choice.message.content:
            blocks.append(ContentBlock(type="text", text=choice.message.content))
        for tc in choice.message.tool_calls or []:
            blocks.append(
                ContentBlock(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        input=json.loads(tc.function.arguments),
                    ),
                )
            )

        usage = resp.usage
        return AgentLLMResponse(
            stop_reason=stop_reason,
            content_blocks=blocks,
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
        )

    @staticmethod
    def _to_oai_agent_messages(
        messages: list[dict[str, Any]], system: str | None
    ) -> list[dict[str, Any]]:
        """Convert agent loop messages (Anthropic format) to OpenAI chat format.

        The agent loop uses Anthropic-style content blocks:
          - assistant turn: list of {type: text|tool_use, ...}
          - tool results:   user turn with [{type: tool_result, tool_use_id, content}]

        OpenAI expects:
          - assistant turn: {role, content, tool_calls: [{id, type, function: {name, arguments}}]}
          - tool result:    {role: "tool", content, tool_call_id}  — one per call
        """
        result: list[dict[str, Any]] = []
        if system:
            result.append({"role": "system", "content": system})

        for msg in messages:
            role: str = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            # content is a list of blocks
            if role == "assistant":
                text_parts = [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
                tool_calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {
                            "name": b["name"],
                            "arguments": json.dumps(b["input"]),
                        },
                    }
                    for b in content
                    if b.get("type") == "tool_use"
                ]
                oai_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": " ".join(text_parts) or None,
                }
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                result.append(oai_msg)

            elif role == "user":
                tool_results = [b for b in content if b.get("type") == "tool_result"]
                if tool_results:
                    # Each tool result is a separate "tool" role message in OpenAI
                    for tr in tool_results:
                        result.append({
                            "role": "tool",
                            "content": tr["content"],
                            "tool_call_id": tr["tool_use_id"],
                        })
                else:
                    result.append({"role": "user", "content": str(content)})

        return result
