from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal

import tiktoken

from app.llm.base import BaseLLMProvider, LLMMessage
from app.prompts.conflict import CONFLICT_CHECK_SYSTEM
from app.rag.query_processor import QueryType
from app.rag.sparse import build_sparse_vector
from app.vectordb.qdrant import QdrantVectorDB, SearchResult

# ── Token budget ──────────────────────────────────────────────────────────────

_TOKENIZER = tiktoken.get_encoding("cl100k_base")
MAX_CONTEXT_TOKENS = 1200
SCORE_THRESHOLD = 0.35

ChainStrategy = Literal["compare", "chain", "aggregate"]


def _count_tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text))


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class AssembledChunk:
    index: int
    text: str
    doc_title: str
    section_title: str
    source_file: str
    score: float
    token_count: int
    sub_query_indices: frozenset[int] = field(default_factory=frozenset)
    primary_sub_query: int = 0


@dataclass
class ConflictPair:
    chunk_a_index: int
    chunk_b_index: int
    topic: str


# ── Query embedding ───────────────────────────────────────────────────────────

async def embed_query(question: str, provider: BaseLLMProvider) -> list[float]:
    vectors = await provider.embed([question])
    return vectors[0]


# ── Hybrid search ─────────────────────────────────────────────────────────────

async def hybrid_search_one(
    query_str: str,
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    limit: int = 5,
    score_threshold: float = SCORE_THRESHOLD,
) -> list[SearchResult]:
    dense_vec = await embed_query(query_str, provider)
    sparse_vec = build_sparse_vector(query_str)
    results = await qdrant.hybrid_search(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        limit=limit,
        prefetch_limit=20,
    )
    return [r for r in results if r.score >= score_threshold]


async def parallel_hybrid_search(
    sub_questions: list[str],
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    limit_per_query: int = 5,
) -> list[list[SearchResult]]:
    """Run hybrid search for all sub-queries concurrently. Returns per-query results."""
    sparse_vecs = [build_sparse_vector(q) for q in sub_questions]
    dense_vecs: list[list[float]] = await asyncio.gather(
        *[embed_query(q, provider) for q in sub_questions]
    )
    results_per_query: list[list[SearchResult]] = list(
        await asyncio.gather(*[
            qdrant.hybrid_search(
                dense_vector=dense,
                sparse_vector=sparse,
                limit=limit_per_query,
                prefetch_limit=20,
            )
            for dense, sparse in zip(dense_vecs, sparse_vecs)
        ])
    )
    return results_per_query


# ── RRF merge + diversity filter ──────────────────────────────────────────────

def rrf_merge(
    results_per_query: list[list[SearchResult]],
    k: int = 60,
    final_limit: int = 5,
    score_threshold: float = SCORE_THRESHOLD,
) -> list[SearchResult]:
    rrf_scores: dict[str, float] = {}
    by_id: dict[str, SearchResult] = {}

    for results in results_per_query:
        for rank, r in enumerate(results, start=1):
            rrf_scores[r.id] = rrf_scores.get(r.id, 0.0) + 1.0 / (k + rank)
            if r.id not in by_id or r.score > by_id[r.id].score:
                by_id[r.id] = r

    ranked_ids = sorted(
        [cid for cid in by_id if by_id[cid].score >= score_threshold],
        key=lambda cid: rrf_scores[cid],
        reverse=True,
    )
    return [by_id[cid] for cid in ranked_ids[:final_limit]]


def apply_diversity_filter(
    chunks: list[SearchResult],
    max_per_source: int = 2,
) -> list[SearchResult]:
    counts: dict[str, int] = {}
    result: list[SearchResult] = []
    for chunk in chunks:
        src = chunk.payload.get("source_file", "")
        if counts.get(src, 0) < max_per_source:
            result.append(chunk)
            counts[src] = counts.get(src, 0) + 1
    return result


# ── Unified retrieval entry point ─────────────────────────────────────────────

async def retrieve(
    sub_questions: list[str],
    query_type: QueryType,
    provider: BaseLLMProvider,
    qdrant: QdrantVectorDB,
    max_sources: int = 5,
    score_threshold: float = SCORE_THRESHOLD,
) -> tuple[list[list[SearchResult]], list[SearchResult]]:
    """
    Returns (results_per_query, merged).
    results_per_query: raw per-sub-query lists for context assembly sub-query tagging.
    merged: RRF-merged, diversity-filtered flat list for empty-result routing.
    """
    if query_type == "SIMPLE":
        results = await hybrid_search_one(
            sub_questions[0], provider, qdrant,
            limit=max_sources, score_threshold=score_threshold,
        )
        return [results], results

    results_per_query = await parallel_hybrid_search(
        sub_questions, provider, qdrant, limit_per_query=max_sources,
    )
    merged = rrf_merge(results_per_query, final_limit=max_sources, score_threshold=score_threshold)
    merged = apply_diversity_filter(merged, max_per_source=2)
    return results_per_query, merged


# ── AssembledChunk builder ────────────────────────────────────────────────────

def _build_assembled_chunks(
    results_per_query: list[list[SearchResult]],
) -> list[AssembledChunk]:
    best_score: dict[str, float] = {}
    best_sq: dict[str, int] = {}
    sub_indices: dict[str, set[int]] = {}
    by_id: dict[str, SearchResult] = {}

    for sq_idx, results in enumerate(results_per_query):
        for r in results:
            sub_indices.setdefault(r.id, set()).add(sq_idx)
            if r.id not in best_score or r.score > best_score[r.id]:
                best_score[r.id] = r.score
                best_sq[r.id] = sq_idx
                by_id[r.id] = r

    ordered_ids = sorted(by_id, key=lambda cid: best_score[cid], reverse=True)
    assembled = []
    for i, cid in enumerate(ordered_ids, start=1):
        r = by_id[cid]
        p = r.payload
        text = p.get("text", "")
        assembled.append(AssembledChunk(
            index             = i,
            text              = text,
            doc_title         = p.get("doc_title", "?"),
            section_title     = p.get("section_title", "?"),
            source_file       = p.get("source_file", "?"),
            score             = best_score[cid],
            token_count       = _count_tokens(text),
            sub_query_indices = frozenset(sub_indices[cid]),
            primary_sub_query = best_sq[cid],
        ))
    return assembled


# ── Chunk formatting ──────────────────────────────────────────────────────────

def _format_chunk(chunk: AssembledChunk) -> str:
    header = f"[SOURCE: {chunk.source_file} | Section: {chunk.section_title}]"
    return f"{header}\n{chunk.text}"


def _conflict_tag(chunk: AssembledChunk, conflicts: list[ConflictPair]) -> str:
    related = [
        cp for cp in conflicts
        if cp.chunk_a_index == chunk.index or cp.chunk_b_index == chunk.index
    ]
    if not related:
        return ""
    other_indices = [
        cp.chunk_b_index if cp.chunk_a_index == chunk.index else cp.chunk_a_index
        for cp in related
    ]
    topic = related[0].topic
    refs = ", ".join(f"Source {i}" for i in other_indices)
    return f"⚠ CONFLICTS WITH {refs} (topic: {topic})\n"


def _format_chunk_annotated(chunk: AssembledChunk, conflicts: list[ConflictPair]) -> str:
    tag = _conflict_tag(chunk, conflicts)
    header = f"[SOURCE: {chunk.source_file} | Section: {chunk.section_title}]"
    return f"{header}\n{tag}{chunk.text}"


# ── Strategy selection ────────────────────────────────────────────────────────

def select_chain_strategy(query_type: QueryType) -> ChainStrategy:
    if query_type == "COMPARISON":
        return "compare"
    if query_type == "COMPLEX":
        return "chain"
    return "aggregate"


# ── Strategy: Aggregate ───────────────────────────────────────────────────────

def _format_aggregate(
    chunks: list[AssembledChunk],
    conflicts: list[ConflictPair],
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> tuple[str, list[AssembledChunk]]:
    entries: list[str] = []
    used: list[AssembledChunk] = []
    total = 0

    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        entry = _format_chunk_annotated(chunk, conflicts)
        t = _count_tokens(entry)
        if total + t > max_tokens:
            break
        entries.append(entry)
        used.append(chunk)
        total += t

    block = "[CONTEXT — AGGREGATED]\n\n" + "\n\n".join(entries)
    return block, used


# ── Strategy: Compare ─────────────────────────────────────────────────────────

def _format_compare(
    chunks: list[AssembledChunk],
    sub_questions: list[str],
    conflicts: list[ConflictPair],
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> tuple[str, list[AssembledChunk]]:
    # Identify chunks in cross-side conflicts → move to DISPUTED
    cross_side_conflict_indices: set[int] = set()
    by_index = {c.index: c for c in chunks}
    for cp in conflicts:
        ca = by_index.get(cp.chunk_a_index)
        cb = by_index.get(cp.chunk_b_index)
        if ca and cb and ca.primary_sub_query != cb.primary_sub_query:
            cross_side_conflict_indices.add(ca.index)
            cross_side_conflict_indices.add(cb.index)

    disputed = [c for c in chunks if c.index in cross_side_conflict_indices]
    shared = [c for c in chunks if len(c.sub_query_indices) > 1 and c.index not in cross_side_conflict_indices]
    sides  = [c for c in chunks if len(c.sub_query_indices) == 1 and c.index not in cross_side_conflict_indices]

    by_sq: dict[int, list[AssembledChunk]] = {}
    for c in sides:
        by_sq.setdefault(c.primary_sub_query, []).append(c)
    for sq in by_sq:
        by_sq[sq].sort(key=lambda c: c.score, reverse=True)

    num_sections = len(by_sq) + (1 if disputed else 0) + (1 if shared else 0)
    tokens_per_section = max_tokens // max(num_sections, 1)

    sections: list[str] = []
    used: list[AssembledChunk] = []

    for sq_idx in sorted(by_sq):
        group_chunks = by_sq[sq_idx]
        label = group_chunks[0].doc_title.upper() if group_chunks else f"OPTION {sq_idx + 1}"
        entries: list[str] = []
        section_total = 0
        for chunk in group_chunks:
            entry = _format_chunk(chunk)
            t = _count_tokens(entry)
            if section_total + t > tokens_per_section:
                break
            entries.append(entry)
            used.append(chunk)
            section_total += t
        if entries:
            sections.append(f"=== {label} ===\n" + "\n\n".join(entries))

    if disputed:
        disputed_entries: list[str] = []
        section_total = 0
        for i, chunk in enumerate(disputed):
            if i == 0:
                entry = _format_chunk(chunk)
            else:
                tag = _conflict_tag(chunk, conflicts) or "⚠ CONFLICTS WITH SOURCE ABOVE\n"
                header = f"[SOURCE: {chunk.source_file} | Section: {chunk.section_title}]"
                entry = f"{header}\n{tag}{chunk.text}"
            t = _count_tokens(entry)
            if section_total + t > tokens_per_section:
                break
            disputed_entries.append(entry)
            used.append(chunk)
            section_total += t
        if disputed_entries:
            sections.append("=== DISPUTED ===\n" + "\n\n".join(disputed_entries))

    if shared:
        shared_entries: list[str] = []
        section_total = 0
        for chunk in sorted(shared, key=lambda c: c.score, reverse=True):
            entry = _format_chunk(chunk)
            t = _count_tokens(entry)
            if section_total + t > tokens_per_section:
                break
            shared_entries.append(entry)
            used.append(chunk)
            section_total += t
        if shared_entries:
            sections.append("=== SHARED PRINCIPLES ===\n" + "\n\n".join(shared_entries))

    block = "[CONTEXT — COMPARISON]\n\n" + "\n\n".join(sections)
    return block, used


# ── Strategy: Chain ───────────────────────────────────────────────────────────

def _short_label(text: str, max_len: int = 50) -> str:
    s = text.strip().upper()
    return s[:max_len].rstrip() + ("..." if len(s) > max_len else "")


def _format_chain(
    chunks: list[AssembledChunk],
    sub_questions: list[str],
    conflicts: list[ConflictPair],
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> tuple[str, list[AssembledChunk]]:
    by_sq: dict[int, list[AssembledChunk]] = {}
    for c in chunks:
        by_sq.setdefault(c.primary_sub_query, []).append(c)
    for sq in by_sq:
        by_sq[sq].sort(key=lambda c: c.score, reverse=True)

    num_steps = max(len(by_sq), 1)
    tokens_per_step = max_tokens // num_steps

    sections: list[str] = []
    used: list[AssembledChunk] = []

    for sq_idx in sorted(by_sq):
        sub_label = (
            _short_label(sub_questions[sq_idx])
            if sq_idx < len(sub_questions)
            else f"STEP {sq_idx + 1}"
        )
        entries: list[str] = []
        step_total = 0
        for chunk in by_sq[sq_idx]:
            entry = _format_chunk_annotated(chunk, conflicts)
            t = _count_tokens(entry)
            if step_total + t > tokens_per_step:
                break
            entries.append(entry)
            used.append(chunk)
            step_total += t
        if entries:
            sections.append(f"=== STEP {sq_idx + 1}: {sub_label} ===\n" + "\n\n".join(entries))

    block = "[CONTEXT — CAUSAL CHAIN]\n\n" + "\n\n".join(sections)
    return block, used


# ── Conflict detection ────────────────────────────────────────────────────────

_CONTRADICTION_PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str]]] = [
    (re.compile(r"\bshould\b"),        re.compile(r"\bshould not\b|shouldn't")),
    (re.compile(r"\bincreases?\b"),    re.compile(r"\bdecreases?\b")),
    (re.compile(r"\bis safe\b"),       re.compile(r"\bis dangerous\b|is harmful\b")),
    (re.compile(r"\bis effective\b"),  re.compile(r"\bis not effective\b|is ineffective\b")),
    (re.compile(r"\brecommended\b"),   re.compile(r"\bnot recommended\b")),
    (re.compile(r"\bcauses?\b"),       re.compile(r"\bdoes not cause\b|doesn't cause\b")),
]

_CONFLICT_CHECK_SYSTEM = CONFLICT_CHECK_SYSTEM


def _heuristic_conflict(a: AssembledChunk, b: AssembledChunk) -> bool:
    ta, tb = a.text.lower(), b.text.lower()
    for pos_pat, neg_pat in _CONTRADICTION_PATTERNS:
        a_pos = bool(pos_pat.search(ta)) and not bool(neg_pat.search(ta))
        a_neg = bool(neg_pat.search(ta))
        b_pos = bool(pos_pat.search(tb)) and not bool(neg_pat.search(tb))
        b_neg = bool(neg_pat.search(tb))
        if (a_pos and b_neg) or (a_neg and b_pos):
            return True
    return False


def _extract_json_block(raw: str) -> str:
    m = re.search(r"\{.*?\}", raw, re.DOTALL)
    return m.group(0) if m else raw


def detect_conflicts_heuristic(chunks: list[AssembledChunk]) -> list[ConflictPair]:
    conflicts: list[ConflictPair] = []
    for i, a in enumerate(chunks):
        for b in chunks[i + 1:]:
            if a.primary_sub_query == b.primary_sub_query:
                continue
            if _heuristic_conflict(a, b):
                conflicts.append(ConflictPair(a.index, b.index, topic="conflicting claims"))
    return conflicts


async def _llm_conflict_check(
    a: AssembledChunk,
    b: AssembledChunk,
    provider: BaseLLMProvider,
    model: str | None = None,
) -> ConflictPair | None:
    prompt = f"Excerpt A:\n{a.text[:400]}\n\nExcerpt B:\n{b.text[:400]}"
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=prompt)],
        system=_CONFLICT_CHECK_SYSTEM,
        max_tokens=60,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json_block(resp.content))
        if data.get("conflict"):
            topic = data.get("topic") or "conflicting claims"
            return ConflictPair(a.index, b.index, topic)
    except Exception:
        pass
    return None


async def detect_conflicts(
    chunks: list[AssembledChunk],
    provider: BaseLLMProvider | None = None,
    model: str | None = None,
) -> list[ConflictPair]:
    candidates = detect_conflicts_heuristic(chunks)
    if not candidates or provider is None:
        return candidates

    by_index = {c.index: c for c in chunks}
    results = await asyncio.gather(*[
        _llm_conflict_check(by_index[cp.chunk_a_index], by_index[cp.chunk_b_index], provider, model)
        for cp in candidates
    ])
    return [r for r in results if r is not None]


# ── Conflict instruction ──────────────────────────────────────────────────────

def _build_conflict_note(conflicts: list[ConflictPair]) -> str:
    topics = ", ".join(dict.fromkeys(cp.topic for cp in conflicts))
    return (
        "\n\n[⚠ CONFLICTING SOURCES DETECTED]\n"
        f"Sources disagree on: {topics}.\n"
        "In your answer, present both perspectives explicitly and acknowledge "
        "that the sources disagree. Do not pick one side without noting the disagreement."
    )


# ── Unified context assembly entry point ─────────────────────────────────────

async def assemble_context(
    results_per_query: list[list[SearchResult]],
    sub_questions: list[str],
    query_type: QueryType,
    provider: BaseLLMProvider | None = None,
    conflict_model: str | None = None,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> tuple[str, list[AssembledChunk], str, int]:
    """Returns (context, used_chunks, strategy, conflict_count)."""
    chunks    = _build_assembled_chunks(results_per_query)
    conflicts = await detect_conflicts(chunks, provider, model=conflict_model)
    strategy  = select_chain_strategy(query_type)

    if strategy == "compare":
        context, used = _format_compare(chunks, sub_questions, conflicts, max_tokens)
    elif strategy == "chain":
        context, used = _format_chain(chunks, sub_questions, conflicts, max_tokens)
    else:
        context, used = _format_aggregate(chunks, conflicts, max_tokens)

    if conflicts:
        context += _build_conflict_note(conflicts)

    return context, used, strategy, len(conflicts)
