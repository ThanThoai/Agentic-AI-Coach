from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.llm.factory import get_default_embedder, get_default_llm
from app.rag.guardrails import (
    BORDERLINE_DISCLAIMER,
    OUT_OF_SCOPE_MESSAGE,
    RESPONSE_EATING_RISK,
    RESPONSE_MEDICAL_REFUSE,
    RESPONSE_OUT_OF_SCOPE,
    classify_intent,
    filter_output,
    hard_block_check,
    needs_intent_classification,
)
from app.rag.query_processor import QueryType, process_query
from app.rag.retriever import AssembledChunk, assemble_context, retrieve
from app.rag.schemas import RAGQuery, RAGResponse, RAGSource
from app.vectordb.qdrant import QdrantVectorDB

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

# ── Generation prompts ────────────────────────────────────────────────────────

GENERATION_SYSTEM_PROMPT = """\
You are a fitness coach assistant. Answer questions using ONLY the information
provided in the numbered context sections below.

Rules:
1. Base every claim on the context. Cite sources using [N] inline.
2. If the context does not contain enough information to answer, say:
   "I don't have specific information about that in my knowledge base."
3. If the question is not about fitness, training, exercise, or nutrition, say:
   "This question is outside my fitness knowledge scope."
4. Do not use external knowledge beyond what is in the context.
5. Return your response as JSON: { "answer": "...", "cited_indices": [1, 3] }"""

SYNTHESIS_INSTRUCTION = (
    "\n\nThe context above covers multiple sub-topics. Synthesise a unified answer "
    "that addresses all parts of the question. Cite sources for each distinct "
    "sub-claim using [N] notation."
)

# ── Generation ────────────────────────────────────────────────────────────────

async def generate(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
) -> LLMResponse:
    system = GENERATION_SYSTEM_PROMPT
    if query_type in ("COMPLEX", "COMPARISON"):
        system += SYNTHESIS_INSTRUCTION
    full_system = system + "\n\n" + context

    return await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=full_system,
        max_tokens=512,
        temperature=0.2,
    )


async def generate_stream(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
) -> AsyncIterator[str]:
    system = GENERATION_SYSTEM_PROMPT
    if query_type in ("COMPLEX", "COMPARISON"):
        system += SYNTHESIS_INSTRUCTION
    full_system = system + "\n\n" + context

    async for token in provider.stream(
        messages=[LLMMessage(role="user", content=question)],
        system=full_system,
        max_tokens=512,
        temperature=0.2,
    ):
        yield token


# ── Source mapping ────────────────────────────────────────────────────────────

def _map_sources(
    used_chunks: list[AssembledChunk],
    cited_indices: list[int],
) -> list[RAGSource]:
    return [
        RAGSource(
            doc_title     = used_chunks[i - 1].doc_title,
            section_title = used_chunks[i - 1].section_title,
            source_file   = used_chunks[i - 1].source_file,
            score         = used_chunks[i - 1].score,
            excerpt       = used_chunks[i - 1].text[:200] + "...",
        )
        for i in cited_indices
        if 1 <= i <= len(used_chunks)
    ]


# ── Dependencies ──────────────────────────────────────────────────────────────

def get_llm_provider() -> BaseLLMProvider:
    return get_default_llm()


def get_embedding_provider() -> BaseLLMProvider:
    return get_default_embedder()


@lru_cache
def _qdrant_singleton() -> QdrantVectorDB:
    from app.core.config import settings
    return QdrantVectorDB.from_url(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection_knowledge,
        api_key=(
            settings.qdrant_api_key.get_secret_value()
            if settings.qdrant_api_key else None
        ),
    )


def get_qdrant() -> QdrantVectorDB:
    return _qdrant_singleton()


# ── Endpoint ──────────────────────────────────────────────────────────────────

_OUT_OF_SCOPE_RESPONSE = RAGResponse(
    answer=RESPONSE_OUT_OF_SCOPE,
    in_scope=False,
    sources=[],
    intent=None,
    model=None,
    usage=None,
)


@router.post("/query", response_model=RAGResponse)
async def query_rag(
    payload: RAGQuery,
    llm: BaseLLMProvider = Depends(get_llm_provider),
    embedder: BaseLLMProvider = Depends(get_embedding_provider),
    qdrant: QdrantVectorDB = Depends(get_qdrant),
) -> RAGResponse:
    question = payload.question

    # ── Layer 1: hard-block rule filter ──────────────────────────────────────
    block_reason = hard_block_check(question)
    if block_reason:
        log.info("rag.hard_block", reason=block_reason)
        return _OUT_OF_SCOPE_RESPONSE

    # ── Layer 2: LLM intent classifier (triggered only for risk signals) ─────
    was_borderline = False
    if needs_intent_classification(question):
        classification = await classify_intent(question, llm)
        intent_label = classification.intent

        if intent_label == "MEDICAL_REFUSE":
            log.info("rag.intent_refused", intent=intent_label)
            return RAGResponse(
                answer=RESPONSE_MEDICAL_REFUSE,
                in_scope=False, sources=[], intent=intent_label,
            )
        if intent_label == "EATING_RISK":
            log.info("rag.intent_refused", intent=intent_label)
            return RAGResponse(
                answer=RESPONSE_EATING_RISK,
                in_scope=False, sources=[], intent=intent_label,
            )
        if intent_label == "OUT_OF_SCOPE":
            log.info("rag.intent_refused", intent=intent_label)
            return _OUT_OF_SCOPE_RESPONSE
        if intent_label == "BORDERLINE":
            was_borderline = True
    else:
        intent_label = None

    # ── Query processing ──────────────────────────────────────────────────────
    query_type, sub_questions = await process_query(question, llm)
    log.info("rag.query_processed", query_type=query_type, num_sub_questions=len(sub_questions))

    # ── Retrieval ─────────────────────────────────────────────────────────────
    results_per_query, merged = await retrieve(
        sub_questions, query_type, embedder, qdrant,
        max_sources=payload.max_sources,
    )

    if not merged:
        log.info("rag.no_results", query_type=query_type)
        return RAGResponse(
            answer=OUT_OF_SCOPE_MESSAGE,
            in_scope=False, sources=[], intent=query_type,
        )

    # ── Context assembly ──────────────────────────────────────────────────────
    context, used_chunks = await assemble_context(
        results_per_query, sub_questions, query_type,
        provider=llm,
    )

    # ── Generation ────────────────────────────────────────────────────────────
    llm_response = await generate(question, context, query_type, llm)
    log.info(
        "rag.generated",
        model=llm_response.model,
        prompt_tokens=llm_response.usage.prompt_tokens,
        completion_tokens=llm_response.usage.completion_tokens,
    )

    # ── Layer 3: output filter ────────────────────────────────────────────────
    answer, cited_indices = filter_output(
        llm_response.content,
        num_chunks=len(used_chunks),
        was_borderline=was_borderline,
    )

    if was_borderline:
        answer += BORDERLINE_DISCLAIMER

    # ── Source mapping ────────────────────────────────────────────────────────
    sources = _map_sources(used_chunks, cited_indices)

    return RAGResponse(
        answer   = answer,
        in_scope = True,
        sources  = sources,
        intent   = query_type,
        model    = llm_response.model,
        usage    = llm_response.usage,
    )
