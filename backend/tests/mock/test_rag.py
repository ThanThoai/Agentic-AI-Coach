"""
Offline tests for the RAG ingestion pipeline.
All external calls (embedding APIs, Qdrant HTTP, BM25 model download) are mocked.
"""
from __future__ import annotations

import textwrap
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.rag.chunker import (
    MIN_TOKENS,
    MAX_TOKENS,
    is_structured_content,
    process_chunks,
    token_count,
)
from app.rag.embedder import build_embed_text, embed_chunks, embed_query
from app.rag.metadata import (
    ChunkMetadata,
    DEFAULT_DIFFICULTY,
    attach_metadata,
    extract_metadata,
)
from app.rag.parser import ParsedChunk, parse_document, parse_all


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_chunk(
    text: str = "## Some Section\nBody text here.",
    doc_title: str = "Test Doc",
    section_title: str = "Some Section",
    source_file: str = "01-bench-press.md",
    chunk_index: str = "0",
    tags: list[str] | None = None,
    topic_type: str = "technique",
    difficulty: list[str] | None = None,
) -> ParsedChunk:
    return ParsedChunk(
        text=text,
        doc_title=doc_title,
        section_title=section_title,
        source_file=source_file,
        chunk_index=chunk_index,
        tags=tags or ["compound", "push"],
        topic_type=topic_type,
        difficulty=difficulty or ["beginner", "intermediate", "advanced"],
    )


@pytest.fixture
def tmp_kb(tmp_path: Path) -> Path:
    """A tiny knowledge-base directory with two markdown files."""
    doc1 = tmp_path / "01-bench-press.md"
    doc1.write_text(
        textwrap.dedent("""\
        # Bench Press

        ## Setup
        Lie flat on the bench, grip slightly wider than shoulder width.

        ## Execution
        Lower the bar to your chest, then press it back up.

        ## Key Mistakes
        Flaring elbows, bouncing the bar off the chest.
        """)
    )
    doc2 = tmp_path / "08-progressive-overload.md"
    doc2.write_text(
        textwrap.dedent("""\
        # Progressive Overload

        ## Definition
        Progressive overload means gradually increasing the stress placed on the body.

        ## Methods of Progressive Overload
        Add weight, reps, sets, or decrease rest time.
        """)
    )
    return tmp_path


# ===========================================================================
# parser.py
# ===========================================================================

class TestParser:
    def test_parse_document_sections(self, tmp_kb: Path) -> None:
        chunks = parse_document(tmp_kb / "01-bench-press.md")
        assert len(chunks) == 3
        titles = [c.section_title for c in chunks]
        assert "Setup" in titles
        assert "Execution" in titles
        assert "Key Mistakes" in titles

    def test_parse_document_doc_title(self, tmp_kb: Path) -> None:
        chunks = parse_document(tmp_kb / "01-bench-press.md")
        assert all(c.doc_title == "Bench Press" for c in chunks)

    def test_parse_document_source_file(self, tmp_kb: Path) -> None:
        chunks = parse_document(tmp_kb / "01-bench-press.md")
        assert all(c.source_file == "01-bench-press.md" for c in chunks)

    def test_parse_document_chunk_indices_sequential(self, tmp_kb: Path) -> None:
        chunks = parse_document(tmp_kb / "01-bench-press.md")
        indices = [c.chunk_index for c in chunks]
        assert indices == ["0", "1", "2"]

    def test_parse_all_returns_all_chunks(self, tmp_kb: Path) -> None:
        chunks = parse_all(tmp_kb)
        source_files = {c.source_file for c in chunks}
        assert "01-bench-press.md" in source_files
        assert "08-progressive-overload.md" in source_files

    def test_parse_document_no_h2_fallback(self, tmp_path: Path) -> None:
        doc = tmp_path / "no-headers.md"
        doc.write_text("# Title\n\nSome content without any H2 headers.\n")
        chunks = parse_document(doc)
        assert len(chunks) == 1
        assert chunks[0].section_title == "Title"

    def test_parse_document_content_before_first_h2(self, tmp_path: Path) -> None:
        doc = tmp_path / "intro.md"
        doc.write_text("# Title\n\nPreamble text.\n\n## Section One\nContent.\n")
        chunks = parse_document(doc)
        titles = [c.section_title for c in chunks]
        assert "Overview" in titles

    def test_parse_document_empty_h2_skipped(self, tmp_path: Path) -> None:
        doc = tmp_path / "sparse.md"
        doc.write_text("# Title\n\n## Empty Section\n\n## Real Section\nActual content here.\n")
        chunks = parse_document(doc)
        assert any(c.section_title == "Real Section" for c in chunks)

    def test_parse_document_h3_stays_inside_h2(self, tmp_path: Path) -> None:
        doc = tmp_path / "nested.md"
        doc.write_text(
            "# Title\n\n## Parent\nParent body.\n\n### Child\nChild body.\n\n## Next\nNext.\n"
        )
        chunks = parse_document(doc)
        parent_chunk = next(c for c in chunks if c.section_title == "Parent")
        assert "### Child" in parent_chunk.text
        assert "Child body" in parent_chunk.text


# ===========================================================================
# metadata.py
# ===========================================================================

class TestMetadata:
    def test_extract_metadata_known_file(self) -> None:
        chunk = make_chunk(source_file="01-bench-press.md")
        meta = extract_metadata(chunk)
        assert meta.topic_type == "technique"
        assert "chest" in meta.tags
        assert "compound" in meta.tags

    def test_extract_metadata_difficulty_default(self) -> None:
        chunk = make_chunk(source_file="01-bench-press.md")
        meta = extract_metadata(chunk)
        assert meta.difficulty == DEFAULT_DIFFICULTY

    def test_extract_metadata_difficulty_override(self) -> None:
        chunk = make_chunk(source_file="14-workout-split-ppl.md")
        meta = extract_metadata(chunk)
        assert "advanced" in meta.difficulty
        assert "beginner" not in meta.difficulty

    def test_extract_metadata_programming(self) -> None:
        chunk = make_chunk(source_file="08-progressive-overload.md")
        meta = extract_metadata(chunk)
        assert meta.topic_type == "programming"

    def test_extract_metadata_unknown_file_fallback(self) -> None:
        chunk = make_chunk(source_file="99-unknown-topic.md")
        meta = extract_metadata(chunk)
        assert meta.difficulty == DEFAULT_DIFFICULTY
        assert meta.topic_type == "technique"

    def test_attach_metadata_mutates_chunk(self) -> None:
        chunk = make_chunk(tags=[], topic_type="", difficulty=[])
        meta = ChunkMetadata(tags=["strength"], difficulty=["beginner"], topic_type="programming")
        result = attach_metadata(chunk, meta)
        assert result.tags == ["strength"]
        assert result.difficulty == ["beginner"]
        assert result.topic_type == "programming"
        assert result is chunk  # same object


# ===========================================================================
# chunker.py
# ===========================================================================

class TestChunker:
    def _make_text_of_tokens(self, n: int) -> str:
        """Create approximately n tokens of text."""
        return " ".join(["word"] * n)

    def test_normal_chunk_passes_through(self) -> None:
        text = self._make_text_of_tokens(200)
        chunk = make_chunk(text=text)
        result = process_chunks([chunk])
        assert len(result) == 1
        assert result[0].chunk_index == "0"

    def test_oversized_chunk_is_split(self) -> None:
        text = self._make_text_of_tokens(600)
        chunk = make_chunk(text=text)
        result = process_chunks([chunk])
        assert len(result) >= 2
        assert result[0].chunk_index == "0.0"
        assert result[1].chunk_index == "0.1"

    def test_split_chunks_respect_max_tokens(self) -> None:
        text = self._make_text_of_tokens(700)
        chunk = make_chunk(text=text)
        result = process_chunks([chunk])
        for r in result:
            assert token_count(r.text) <= MAX_TOKENS

    def test_short_chunk_merged_with_next(self) -> None:
        short = make_chunk(
            text=self._make_text_of_tokens(30),
            section_title="Short",
            chunk_index="0",
        )
        nxt = make_chunk(
            text=self._make_text_of_tokens(100),
            section_title="Next",
            chunk_index="1",
        )
        result = process_chunks([short, nxt])
        assert len(result) == 1
        assert "Short" in result[0].section_title
        assert "Next" in result[0].section_title

    def test_last_short_chunk_merged_with_previous(self) -> None:
        normal = make_chunk(
            text=self._make_text_of_tokens(100),
            section_title="Normal",
            chunk_index="0",
        )
        short = make_chunk(
            text=self._make_text_of_tokens(20),
            section_title="Short",
            chunk_index="1",
        )
        result = process_chunks([normal, short])
        assert len(result) == 1

    def test_single_short_chunk_kept(self) -> None:
        chunk = make_chunk(text=self._make_text_of_tokens(20))
        result = process_chunks([chunk])
        assert len(result) == 1

    def test_is_structured_content_table(self) -> None:
        text = "\n".join(["| col1 | col2 |", "|------|------|"] + ["| a | b |"] * 8)
        assert is_structured_content(text) is True

    def test_is_structured_content_normal(self) -> None:
        text = "This is normal prose.\n" * 10
        assert is_structured_content(text) is False

    def test_overlap_in_split_chunks(self) -> None:
        # Build a longer text so we get two sub-chunks and can verify overlap
        words = ["word"] * 600
        text = " ".join(words)
        chunk = make_chunk(text=text)
        result = process_chunks([chunk])
        assert len(result) >= 2
        # The tail of the first sub-chunk should appear in the start of the second
        tail_tokens = result[0].text.split()[-10:]
        head_tokens = result[1].text.split()[:10]
        overlap = set(tail_tokens) & set(head_tokens)
        assert len(overlap) > 0


# ===========================================================================
# embedder.py
# ===========================================================================

class TestEmbedder:
    def test_build_embed_text_contains_prefix(self) -> None:
        chunk = make_chunk(
            doc_title="Progressive Overload",
            section_title="Rate of Progression",
            topic_type="programming",
            tags=["progressive_overload", "strength"],
        )
        text = build_embed_text(chunk)
        assert "Document: Progressive Overload" in text
        assert "Section: Rate of Progression" in text
        assert "Type: programming" in text
        assert "Tags: progressive_overload, strength" in text

    def test_build_embed_text_contains_chunk_body(self) -> None:
        chunk = make_chunk(text="## Section\nBody content here.")
        text = build_embed_text(chunk)
        assert "Body content here" in text

    def test_build_embed_text_prefix_before_body(self) -> None:
        chunk = make_chunk(
            text="## Section\nBody.",
            doc_title="Doc",
            section_title="Sec",
        )
        text = build_embed_text(chunk)
        prefix_end = text.index("\n\n")
        assert "Document: Doc" in text[:prefix_end]
        assert "Body." in text[prefix_end:]

    @pytest.mark.asyncio
    async def test_embed_chunks_calls_provider(self) -> None:
        from tests.mock.conftest import MockLLMProvider

        provider = MockLLMProvider()
        chunks = [make_chunk(chunk_index=str(i)) for i in range(3)]
        pairs = await embed_chunks(chunks, provider)
        assert len(pairs) == 3
        for chunk, vec in pairs:
            assert isinstance(vec, list)
            assert len(vec) == 5  # MockLLMProvider returns 5-dim vectors

    @pytest.mark.asyncio
    async def test_embed_chunks_batches_correctly(self) -> None:
        from tests.mock.conftest import MockLLMProvider

        provider = MockLLMProvider()
        chunks = [make_chunk(chunk_index=str(i)) for i in range(75)]
        pairs = await embed_chunks(chunks, provider, batch_size=50)
        assert len(pairs) == 75

    @pytest.mark.asyncio
    async def test_embed_query_returns_vector(self) -> None:
        from tests.mock.conftest import MockLLMProvider

        provider = MockLLMProvider()
        vec = await embed_query("how do I bench press?", provider)
        assert isinstance(vec, list)
        assert len(vec) > 0


# ===========================================================================
# ingestion.py — chunk_id
# ===========================================================================

class TestChunkId:
    def test_chunk_id_deterministic(self) -> None:
        from app.rag.ingestion import chunk_id

        id1 = chunk_id("08-progressive-overload.md", "2")
        id2 = chunk_id("08-progressive-overload.md", "2")
        assert id1 == id2

    def test_chunk_id_different_files(self) -> None:
        from app.rag.ingestion import chunk_id

        id1 = chunk_id("01-bench-press.md", "0")
        id2 = chunk_id("08-progressive-overload.md", "0")
        assert id1 != id2

    def test_chunk_id_different_indices(self) -> None:
        from app.rag.ingestion import chunk_id

        id1 = chunk_id("01-bench-press.md", "0")
        id2 = chunk_id("01-bench-press.md", "1")
        assert id1 != id2

    def test_chunk_id_is_valid_uuid(self) -> None:
        import uuid as _uuid
        from app.rag.ingestion import chunk_id

        result = chunk_id("file.md", "0")
        parsed = _uuid.UUID(result)
        assert str(parsed) == result


# ===========================================================================
# Qdrant hybrid collection (in-memory)
# ===========================================================================

@pytest.fixture
async def hybrid_db():
    from app.vectordb.qdrant import QdrantVectorDB

    db = QdrantVectorDB.from_url(":memory:", "kb_hybrid")
    await db.ensure_collection_hybrid(dense_size=5)
    return db


class TestHybridCollection:
    @pytest.mark.asyncio
    async def test_ensure_collection_hybrid_idempotent(self, hybrid_db) -> None:
        # Should not raise when called a second time
        await hybrid_db.ensure_collection_hybrid(dense_size=5)

    @pytest.mark.asyncio
    async def test_upsert_and_count(self, hybrid_db) -> None:
        from qdrant_client.models import SparseVector

        dense = [[0.1, 0.2, 0.3, 0.4, 0.5]]
        sparse = [SparseVector(indices=[1, 5, 10], values=[1.0, 0.5, 0.8])]
        payloads = [{"text": "bench press technique", "source_file": "01-bench-press.md"}]

        await hybrid_db.upsert_hybrid(
            dense_vectors=dense,
            sparse_vectors=sparse,
            payloads=payloads,
        )
        count = await hybrid_db.count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, hybrid_db) -> None:
        from qdrant_client.models import SparseVector

        dense = [[0.1, 0.2, 0.3, 0.4, 0.5]]
        sparse = [SparseVector(indices=[1, 5], values=[1.0, 0.5])]
        ids = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]

        await hybrid_db.upsert_hybrid(
            dense_vectors=dense,
            sparse_vectors=sparse,
            payloads=[{"text": "first"}],
            ids=ids,
        )
        await hybrid_db.upsert_hybrid(
            dense_vectors=dense,
            sparse_vectors=sparse,
            payloads=[{"text": "updated"}],
            ids=ids,
        )
        count = await hybrid_db.count()
        assert count == 1  # upsert does not duplicate

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self, hybrid_db) -> None:
        from qdrant_client.models import SparseVector

        # Insert two points
        dense_vecs = [
            [0.9, 0.1, 0.1, 0.1, 0.1],
            [0.1, 0.9, 0.1, 0.1, 0.1],
        ]
        sparse_vecs = [
            SparseVector(indices=[0, 1], values=[2.0, 1.0]),
            SparseVector(indices=[2, 3], values=[2.0, 1.0]),
        ]
        payloads = [
            {"text": "bench press", "source_file": "01-bench-press.md"},
            {"text": "squat", "source_file": "02-squat.md"},
        ]
        await hybrid_db.upsert_hybrid(
            dense_vectors=dense_vecs,
            sparse_vectors=sparse_vecs,
            payloads=payloads,
        )

        # Query with a vector similar to the first point
        q_dense = [0.85, 0.1, 0.1, 0.1, 0.1]
        q_sparse = SparseVector(indices=[0, 1], values=[1.5, 0.8])
        results = await hybrid_db.hybrid_search(
            dense_vector=q_dense,
            sparse_vector=q_sparse,
            limit=2,
        )
        assert len(results) >= 1
        assert results[0].payload.get("source_file") == "01-bench-press.md"
