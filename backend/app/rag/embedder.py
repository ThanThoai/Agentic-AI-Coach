from __future__ import annotations

from itertools import islice
from typing import TYPE_CHECKING, Iterable, Iterator, TypeVar

if TYPE_CHECKING:
    from app.llm.base import BaseLLMProvider

from app.rag.parser import ParsedChunk

T = TypeVar("T")

DEFAULT_BATCH_SIZE = 50


def _batched(iterable: Iterable[T], n: int) -> Iterator[list[T]]:
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def build_embed_text(chunk: ParsedChunk) -> str:
    """Prepend contextual breadcrumb prefix to chunk text for embedding only."""
    tags_csv = ", ".join(chunk.tags) if chunk.tags else ""
    prefix = (
        f"Document: {chunk.doc_title} | "
        f"Section: {chunk.section_title} | "
        f"Type: {chunk.topic_type} | "
        f"Tags: {tags_csv}"
    )
    return f"{prefix}\n\n{chunk.text}"


async def embed_chunks(
    chunks: list[ParsedChunk],
    provider: BaseLLMProvider,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[tuple[ParsedChunk, list[float]]]:
    """Embed all chunks in batches. Returns (chunk, dense_vector) pairs."""
    results: list[tuple[ParsedChunk, list[float]]] = []
    for batch in _batched(chunks, batch_size):
        embed_texts = [build_embed_text(c) for c in batch]
        vectors = await provider.embed(embed_texts)
        results.extend(zip(batch, vectors))
    return results


async def embed_query(question: str, provider: BaseLLMProvider) -> list[float]:
    """Embed a single user question (no prefix — query uses its own phrasing)."""
    vectors = await provider.embed([question])
    return vectors[0]
