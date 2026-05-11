from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)


@dataclass
class SearchResult:
    id: str
    score: float
    payload: dict[str, Any]


class QdrantVectorDB:
    """Async Qdrant client wrapper with collection lifecycle helpers."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str) -> None:
        self._client = client
        self.collection = collection_name

    @classmethod
    def from_url(
        cls,
        url: str,
        collection_name: str,
        api_key: str | None = None,
    ) -> "QdrantVectorDB":
        """Factory: connect by URL. Supports ':memory:' for in-memory mode."""
        if url == ":memory:":
            client = AsyncQdrantClient(":memory:")
        else:
            client = AsyncQdrantClient(url=url, api_key=api_key or None)
        return cls(client, collection_name)

    async def ensure_collection(self, vector_size: int, distance: Distance = Distance.COSINE) -> None:
        """Create the collection if it does not already exist."""
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if self.collection not in existing:
            await self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=vector_size, distance=distance),
            )

    async def upsert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Upsert vectors. Auto-generates UUIDs if ids not provided."""
        point_ids = ids or [str(uuid4()) for _ in vectors]
        points = [
            PointStruct(id=pid, vector=vec, payload=payload)
            for pid, vec, payload in zip(point_ids, vectors, payloads)
        ]
        await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        return point_ids

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float = 0.0,
        filter_by: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Nearest-neighbour search with optional payload filter."""
        query_filter: Filter | None = None
        if filter_by:
            query_filter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filter_by.items()
                ]
            )

        hits: list[ScoredPoint] = await self._client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            SearchResult(id=str(h.id), score=h.score, payload=h.payload or {})
            for h in hits
        ]

    async def delete(self, ids: list[str]) -> None:
        from qdrant_client.models import PointIdsList
        await self._client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=ids),
            wait=True,
        )

    async def count(self) -> int:
        result = await self._client.count(collection_name=self.collection)
        return result.count
