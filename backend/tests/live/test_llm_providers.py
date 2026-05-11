"""
Live integration tests — call real provider APIs.
Run: uv run pytest -m live

Each test auto-skips if its API key is missing in .env.test.
Uses cheapest/fastest models to minimise cost.
"""
import pytest

from app.llm.base import LLMMessage

MESSAGES = [LLMMessage(role="user", content="Reply with exactly: pong")]
SYSTEM = "You are a test assistant. Follow instructions literally."


# ── Anthropic ─────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_anthropic_live_complete(live_anthropic):
    resp = await live_anthropic.complete(MESSAGES, system=SYSTEM, max_tokens=16)
    assert resp.content.strip()
    assert resp.usage.total_tokens > 0
    assert resp.provider == "anthropic"


@pytest.mark.live
async def test_anthropic_live_stream(live_anthropic):
    chunks = []
    async for chunk in live_anthropic.stream(MESSAGES, system=SYSTEM, max_tokens=16):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert "".join(chunks).strip()


# ── OpenAI ────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_openai_live_complete(live_openai):
    resp = await live_openai.complete(MESSAGES, system=SYSTEM, max_tokens=16)
    assert resp.content.strip()
    assert resp.provider == "openai"


@pytest.mark.live
async def test_openai_live_embed(live_openai):
    vectors = await live_openai.embed(["bench press form", "squat depth"])
    assert len(vectors) == 2
    assert len(vectors[0]) > 100  # text-embedding-3-small = 1536 dims


# ── Gemini ────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_gemini_live_complete(live_gemini):
    resp = await live_gemini.complete(MESSAGES, max_tokens=16)
    assert resp.content.strip()
    assert resp.provider == "gemini"


@pytest.mark.live
async def test_gemini_live_embed(live_gemini):
    vectors = await live_gemini.embed(["progressive overload principle"])
    assert len(vectors) == 1
    assert len(vectors[0]) > 100


# ── Grok ──────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_grok_live_complete(live_grok):
    resp = await live_grok.complete(MESSAGES, max_tokens=16)
    assert resp.content.strip()
    assert resp.provider == "grok"


# ── OpenRouter ────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_openrouter_live_complete(live_openrouter):
    resp = await live_openrouter.complete(MESSAGES, max_tokens=16)
    assert resp.content.strip()
    assert resp.provider == "openrouter"


# ── Qdrant ────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_qdrant_live_upsert_search(live_qdrant):
    await live_qdrant.ensure_collection(vector_size=3)
    ids = await live_qdrant.upsert(
        vectors=[[0.1, 0.2, 0.3]],
        payloads=[{"test": True}],
    )
    results = await live_qdrant.search([0.1, 0.2, 0.3], limit=1)
    assert results[0].score > 0.9
    await live_qdrant.delete(ids)
