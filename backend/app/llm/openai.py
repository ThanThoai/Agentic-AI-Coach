from typing import AsyncIterator

from openai import AsyncOpenAI

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, TokenUsage


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
