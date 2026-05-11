"""Offline ingestion pipeline: parse → metadata → chunk → embed → upsert.

Usage:
    uv run python -m app.rag.ingestion
    uv run python -m app.rag.ingestion --force-recreate
    uv run python -m app.rag.ingestion --file knowledge-base/08-progressive-overload.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import time
import uuid
from itertools import islice
from pathlib import Path
from typing import Iterator

log: object  # assigned lazily to avoid importing structlog at module level

DENSE_SIZE = 1536
BATCH_UPSERT = 50

# Lazy module-level logger — initialised the first time run_ingestion() is called
_log = None


def _get_log():
    global _log
    if _log is None:
        import structlog
        _log = structlog.get_logger("rag.ingest")
    return _log


def chunk_id(source_file: str, chunk_index: str) -> str:
    """Deterministic UUID from source_file + chunk_index for idempotent upserts."""
    key = f"{source_file}::{chunk_index}"
    return str(uuid.UUID(hashlib.sha256(key.encode()).hexdigest()[:32]))


def _batched(items: list, n: int) -> Iterator[list]:
    it = iter(items)
    while batch := list(islice(it, n)):
        yield batch


async def _attach_all_metadata(chunks, llm_provider) -> tuple[int, int]:
    """Attach metadata to all chunks. Returns (rule_count, llm_count)."""
    from app.rag.metadata import (
        TOPIC_TYPE_RULES,
        _file_slug,
        _match_rule_key,
        attach_metadata,
        extract_metadata,
        extract_metadata_llm,
    )

    rule_count = 0
    llm_count = 0
    seen_files: dict[str, bool] = {}

    for chunk in chunks:
        slug = _file_slug(chunk.source_file)
        has_rule = _match_rule_key(slug, TOPIC_TYPE_RULES) is not None

        if has_rule:
            attach_metadata(chunk, extract_metadata(chunk))
            if chunk.source_file not in seen_files:
                seen_files[chunk.source_file] = True
                rule_count += 1
        else:
            if chunk.source_file not in seen_files:
                meta = await extract_metadata_llm(chunk, llm_provider)
                seen_files[chunk.source_file] = False
                llm_count += 1
            else:
                meta = extract_metadata(chunk)
            attach_metadata(chunk, meta)

    return rule_count, llm_count


async def run_ingestion(
    kb_dir: Path,
    settings,
    force_recreate: bool = False,
    single_file: Path | None = None,
) -> None:
    from app.llm.factory import build_provider
    from app.rag.chunker import process_chunks
    from app.rag.embedder import embed_chunks
    from app.rag.parser import parse_all, parse_document
    from app.rag.sparse import build_sparse_vectors_batch
    from app.vectordb.qdrant import QdrantVectorDB

    log = _get_log()
    t0 = time.monotonic()

    # --- Parse ---
    if single_file is not None:
        raw_chunks = parse_document(single_file)
    else:
        raw_chunks = parse_all(kb_dir)

    log.info("parsed", docs_found=len({c.source_file for c in raw_chunks}), chunks_parsed=len(raw_chunks))

    # --- Metadata ---
    llm_provider = build_provider(settings.default_llm_provider, settings)
    embed_provider = build_provider(settings.default_embedding_provider, settings)

    rule_count, llm_count = await _attach_all_metadata(raw_chunks, llm_provider)
    log.info(
        "metadata_extracted",
        total=len({c.source_file for c in raw_chunks}),
        strategy="rule_based",
        llm_fallback=llm_count,
    )

    # --- Chunking ---
    chunks = process_chunks(raw_chunks)
    log.info("chunking_done", final_chunks=len(chunks))

    # --- Dense embedding ---
    t_embed = time.monotonic()
    chunk_vector_pairs = await embed_chunks(chunks, embed_provider)
    embed_ms = int((time.monotonic() - t_embed) * 1000)
    total_embed_tokens = sum(len(c.text.split()) for c, _ in chunk_vector_pairs)
    log.info(
        "dense_embedded",
        chunks=len(chunk_vector_pairs),
        approx_tokens=total_embed_tokens,
        duration_ms=embed_ms,
    )

    # --- Sparse (BM25) ---
    t_sparse = time.monotonic()
    sparse_texts = [c.text for c, _ in chunk_vector_pairs]
    sparse_vectors = build_sparse_vectors_batch(sparse_texts)
    sparse_ms = int((time.monotonic() - t_sparse) * 1000)
    log.info("sparse_embedded", chunks=len(sparse_vectors), duration_ms=sparse_ms, api_cost_usd=0.00)

    # --- Qdrant upsert ---
    db = QdrantVectorDB.from_url(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection_knowledge,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
    )

    if force_recreate:
        await db.recreate_collection_hybrid(dense_size=DENSE_SIZE)
        log.info("collection_recreated", name=settings.qdrant_collection_knowledge)
    else:
        await db.ensure_collection_hybrid(dense_size=DENSE_SIZE)

    upserted = 0
    for batch_items in _batched(list(zip(chunk_vector_pairs, sparse_vectors)), BATCH_UPSERT):
        cv_pairs, sv_batch = zip(*[(item[0], item[1]) for item in batch_items])
        batch_chunks = [chunk for chunk, _ in cv_pairs]
        batch_dense = [vec for _, vec in cv_pairs]
        batch_sparse = list(sv_batch)

        payloads = [
            {
                "source_file": c.source_file,
                "doc_title": c.doc_title,
                "section_title": c.section_title,
                "chunk_index": c.chunk_index,
                "text": c.text,
                "topic_type": c.topic_type,
                "difficulty": c.difficulty,
                "tags": c.tags,
            }
            for c in batch_chunks
        ]
        ids = [chunk_id(c.source_file, c.chunk_index) for c in batch_chunks]

        await db.upsert_hybrid(
            dense_vectors=batch_dense,
            sparse_vectors=batch_sparse,
            payloads=payloads,
            ids=ids,
        )
        upserted += len(ids)

    duration_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "ingestion_complete",
        upserted=upserted,
        collection=settings.qdrant_collection_knowledge,
        duration_ms=duration_ms,
    )


def main() -> None:
    from app.core.config import Settings

    parser = argparse.ArgumentParser(description="Ingest fitness knowledge base into Qdrant.")
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Delete and recreate the Qdrant collection before ingesting.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Ingest a single markdown file instead of the full directory.",
    )
    args = parser.parse_args()

    settings = Settings()
    kb_dir = Path(settings.knowledge_base_path)

    asyncio.run(
        run_ingestion(
            kb_dir=kb_dir,
            settings=settings,
            force_recreate=args.force_recreate,
            single_file=args.file,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
