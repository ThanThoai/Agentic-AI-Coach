from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client.models import SparseVector

_SPARSE_MODEL = None


def _model():
    global _SPARSE_MODEL
    if _SPARSE_MODEL is None:
        from fastembed import SparseTextEmbedding
        _SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _SPARSE_MODEL


def build_sparse_vector(text: str) -> "SparseVector":
    """Compute a BM25 sparse vector for a single text (raw text, no prefix)."""
    from qdrant_client.models import SparseVector

    result = next(_model().embed([text]))
    return SparseVector(
        indices=result.indices.tolist(),
        values=result.values.tolist(),
    )


def build_sparse_vectors_batch(texts: list[str]) -> "list[SparseVector]":
    """Compute BM25 sparse vectors for a batch of texts."""
    from qdrant_client.models import SparseVector

    return [
        SparseVector(indices=r.indices.tolist(), values=r.values.tolist())
        for r in _model().embed(texts)
    ]
