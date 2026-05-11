"""
Mock tests for Qdrant vector DB using in-memory mode.
No real Qdrant server required.
Run: uv run pytest tests/mock/
"""
import pytest


@pytest.mark.mock
async def test_upsert_and_search(vector_db):
    vectors = [[0.1, 0.2, 0.3, 0.4, 0.5], [0.9, 0.8, 0.7, 0.6, 0.5]]
    payloads = [
        {"exercise": "bench_press", "topic": "form"},
        {"exercise": "squat", "topic": "safety"},
    ]
    ids = await vector_db.upsert(vectors, payloads)
    assert len(ids) == 2

    results = await vector_db.search(query_vector=[0.1, 0.2, 0.3, 0.4, 0.5], limit=2)
    assert len(results) >= 1
    assert results[0].score > 0.9  # first result should match closely


@pytest.mark.mock
async def test_search_with_filter(vector_db):
    vectors = [[0.1, 0.2, 0.3, 0.4, 0.5], [0.1, 0.2, 0.3, 0.4, 0.5]]
    payloads = [{"type": "knowledge"}, {"type": "workout"}]
    await vector_db.upsert(vectors, payloads)

    results = await vector_db.search(
        query_vector=[0.1, 0.2, 0.3, 0.4, 0.5],
        limit=5,
        filter_by={"type": "knowledge"},
    )
    assert all(r.payload["type"] == "knowledge" for r in results)


@pytest.mark.mock
async def test_delete(vector_db):
    ids = await vector_db.upsert([[0.1, 0.2, 0.3, 0.4, 0.5]], [{"note": "temp"}])
    count_before = await vector_db.count()
    await vector_db.delete(ids)
    count_after = await vector_db.count()
    assert count_after == count_before - 1


@pytest.mark.mock
async def test_count_empty(vector_db):
    count = await vector_db.count()
    assert count == 0
