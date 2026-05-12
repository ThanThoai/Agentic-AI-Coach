from openai import AsyncOpenAI

from app.llm.base import LLMMessage, LLMResponse, TokenUsage
from app.llm.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter — routes to 100+ models via OpenAI-compatible API."""

    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        default_model: str = "anthropic/claude-sonnet-4-5",
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: str = "http://localhost:3000",
        site_name: str = "CoachAgent",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
        self._default_model = default_model
        # OpenRouter does not support the embeddings API —
        # use DEFAULT_EMBEDDING_PROVIDER=openai alongside this provider.
        self._embedding_model = ""

    async def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> LLMResponse:
        """Force JSON output via assistant prefill instead of response_format.

        response_format={"type": "json_object"} is not supported by all models
        available through OpenRouter (notably google/gemini-* variants).  The
        prefill approach — appending an assistant turn that starts with "{" —
        works universally: the model is forced to continue from inside a JSON
        object and cannot emit preamble text.
        """
        api_messages = self._to_oai_messages(messages, system)
        api_messages.append({"role": "assistant", "content": "{"})

        resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=model or self._default_model,
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content="{" + (choice.message.content or ""),
            model=resp.model,
            provider=self.provider_name,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
        )
