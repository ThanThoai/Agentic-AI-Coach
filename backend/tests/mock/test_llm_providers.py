"""
Mock tests for all LLM providers.
All HTTP calls are intercepted — no real API keys required.
Run: uv run pytest tests/mock/
"""
import json
import pytest
import respx
import httpx

from app.llm.base import LLMMessage, TokenUsage
from app.llm.anthropic import AnthropicProvider
from app.llm.openai import OpenAIProvider
from app.llm.grok import GrokProvider
from app.llm.openrouter import OpenRouterProvider


MESSAGES = [LLMMessage(role="user", content="What is progressive overload?")]
SYSTEM = "You are a fitness coach."


# ── Anthropic ─────────────────────────────────────────────────────────────────

@pytest.mark.mock
@respx.mock
async def test_anthropic_complete():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Progressive overload means gradually increasing stress."}],
            "model": "claude-haiku-4-5-20251001",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 15, "output_tokens": 12, "cache_read_input_tokens": 0},
        })
    )
    provider = AnthropicProvider(api_key="sk-ant-fake", default_model="claude-haiku-4-5-20251001")
    resp = await provider.complete(MESSAGES, system=SYSTEM)

    assert "progressive overload" in resp.content.lower()
    assert resp.provider == "anthropic"
    assert resp.usage.total_tokens == 27


# ── OpenAI ────────────────────────────────────────────────────────────────────

@pytest.mark.mock
@respx.mock
async def test_openai_complete():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "chatcmpl-01",
            "object": "chat.completion",
            "model": "gpt-4o-mini",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Progressive overload is key."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 7, "total_tokens": 22},
        })
    )
    provider = OpenAIProvider(api_key="sk-fake", default_model="gpt-4o-mini")
    resp = await provider.complete(MESSAGES, system=SYSTEM)

    assert resp.content == "Progressive overload is key."
    assert resp.provider == "openai"
    assert resp.usage.total_tokens == 22


@pytest.mark.mock
@respx.mock
async def test_openai_embed():
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json={
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        })
    )
    provider = OpenAIProvider(api_key="sk-fake")
    vectors = await provider.embed(["test text"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 3


# ── Grok ──────────────────────────────────────────────────────────────────────

@pytest.mark.mock
@respx.mock
async def test_grok_complete():
    respx.post("https://api.x.ai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "grok-01",
            "object": "chat.completion",
            "model": "grok-beta",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Train harder each week."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })
    )
    provider = GrokProvider(api_key="xai-fake")
    resp = await provider.complete(MESSAGES)

    assert resp.provider == "grok"
    assert resp.usage.total_tokens == 15


# ── OpenRouter ────────────────────────────────────────────────────────────────

@pytest.mark.mock
@respx.mock
async def test_openrouter_complete():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "or-01",
            "object": "chat.completion",
            "model": "anthropic/claude-3-haiku",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Consistency beats intensity."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        })
    )
    provider = OpenRouterProvider(api_key="sk-or-fake")
    resp = await provider.complete(MESSAGES)

    assert resp.provider == "openrouter"
    assert "consistency" in resp.content.lower()


# ── Factory ───────────────────────────────────────────────────────────────────

@pytest.mark.mock
def test_factory_builds_correct_provider():
    import os
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fake"

    from app.core.config import LLMProvider, Settings
    from app.llm.factory import build_provider
    from app.llm.anthropic import AnthropicProvider

    cfg = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/test",
        jwt_secret="test-secret-that-is-long-enough-here",
        anthropic_api_key="sk-ant-fake",
        default_llm_provider=LLMProvider.ANTHROPIC,
    )
    provider = build_provider(LLMProvider.ANTHROPIC, cfg)
    assert isinstance(provider, AnthropicProvider)
