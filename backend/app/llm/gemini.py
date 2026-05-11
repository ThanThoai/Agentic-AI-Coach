from typing import AsyncIterator

import google.generativeai as genai

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, TokenUsage


class GeminiProvider(BaseLLMProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str, default_model: str = "gemini-1.5-pro") -> None:
        genai.configure(api_key=api_key)
        self._default_model = default_model

    def _build_history(self, messages: list[LLMMessage]) -> tuple[list[dict], str]:
        """Split messages into Gemini history format + last user turn."""
        history: list[dict] = []
        for m in messages[:-1]:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            history.append({"role": role, "parts": [m.content]})
        last = messages[-1].content if messages else ""
        return history, last

    def _get_system(self, messages: list[LLMMessage], system: str | None) -> str | None:
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
        sys_instruction = self._get_system(messages, system)
        gen_model = genai.GenerativeModel(
            model_name=model or self._default_model,
            system_instruction=sys_instruction,
            generation_config=genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        history, last_turn = self._build_history(messages)
        chat = gen_model.start_chat(history=history)
        resp = await chat.send_message_async(last_turn)
        usage = resp.usage_metadata
        return LLMResponse(
            content=resp.text,
            model=model or self._default_model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_token_count if usage else 0,
                completion_tokens=usage.candidates_token_count if usage else 0,
                total_tokens=usage.total_token_count if usage else 0,
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
        sys_instruction = self._get_system(messages, system)
        gen_model = genai.GenerativeModel(
            model_name=model or self._default_model,
            system_instruction=sys_instruction,
            generation_config=genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        history, last_turn = self._build_history(messages)
        chat = gen_model.start_chat(history=history)
        async for chunk in await chat.send_message_async(last_turn, stream=True):
            if chunk.text:
                yield chunk.text

    async def embed(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        embed_model = model or "models/text-embedding-004"
        results: list[list[float]] = []
        for text in texts:
            resp = genai.embed_content(model=embed_model, content=text)
            results.append(resp["embedding"])
        return results
