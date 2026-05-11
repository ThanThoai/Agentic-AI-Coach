"""
Mock test fixtures.
All external HTTP calls (LLM APIs, Qdrant HTTP) are intercepted — no real keys needed.
"""
import pytest
import respx
import httpx

from app.llm.base import LLMMessage, LLMResponse, TokenUsage


# ── LLM provider stubs ────────────────────────────────────────────────────────

MOCK_RESPONSE = LLMResponse(
    content="This is a mock coaching response.",
    model="mock-model",
    provider="mock",
    usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
)

MOCK_EMBEDDING = [[0.1, 0.2, 0.3, 0.4, 0.5]]


class MockLLMProvider:
    """Drop-in replacement for any BaseLLMProvider in unit tests."""

    provider_name = "mock"

    async def complete(self, messages, *, model=None, max_tokens=2048, temperature=0.7, system=None):
        return MOCK_RESPONSE

    async def stream(self, messages, *, model=None, max_tokens=2048, temperature=0.7, system=None):
        for word in MOCK_RESPONSE.content.split():
            yield word + " "

    async def embed(self, texts, *, model=None):
        return [MOCK_EMBEDDING[0] for _ in texts]


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


# ── Qdrant in-memory fixture ───────────────────────────────────────────────────

@pytest.fixture
async def vector_db():
    from app.vectordb.qdrant import QdrantVectorDB
    db = QdrantVectorDB.from_url(":memory:", "test_collection")
    await db.ensure_collection(vector_size=5)
    return db
