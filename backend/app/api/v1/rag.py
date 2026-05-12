from __future__ import annotations

import json
from functools import lru_cache
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.llm.factory import PipelineProviders, get_default_embedder, get_default_llm
from app.prompts.generation import GENERATION_STREAM_SYSTEM, GENERATION_SYSTEM, SYNTHESIS_INSTRUCTION
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
from app.rag.schemas import (
    ContextTrace,
    GuardrailL1Trace,
    GuardrailL2Trace,
    PipelineTrace,
    QueryProcessorTrace,
    RAGQuery,
    RAGResponse,
    RAGSource,
    RetrievalTrace,
)
from app.vectordb.qdrant import QdrantVectorDB

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

# ── Generation prompts ────────────────────────────────────────────────────────

GENERATION_SYSTEM_PROMPT = GENERATION_SYSTEM

# ── Generation ────────────────────────────────────────────────────────────────

async def generate(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
    model: str | None = None,
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
        model=model,
    )


async def generate_stream(
    question: str,
    context: str,
    query_type: QueryType,
    provider: BaseLLMProvider,
    model: str | None = None,
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
        model=model,
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

def get_pipeline_providers() -> PipelineProviders:
    from app.core.config import settings
    return PipelineProviders(settings)


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

@router.post("/query", response_model=RAGResponse)
async def query_rag(
    payload: RAGQuery,
    providers: PipelineProviders = Depends(get_pipeline_providers),
    qdrant: QdrantVectorDB = Depends(get_qdrant),
) -> RAGResponse:
    question = payload.question

    # ── Layer 1: hard-block rule filter ──────────────────────────────────────
    block_reason = hard_block_check(question)
    if block_reason:
        log.info("rag.hard_block", reason=block_reason)
        return RAGResponse(
            answer=RESPONSE_OUT_OF_SCOPE,
            in_scope=False,
            sources=[],
            trace=PipelineTrace(
                guardrail_l1=GuardrailL1Trace(status="blocked", block_reason=block_reason),
            ),
        )

    l1_trace = GuardrailL1Trace(status="passed")

    # ── Layer 2: LLM intent classifier (triggered only for risk signals) ─────
    was_borderline = False
    l2_trace: GuardrailL2Trace | None = None

    if needs_intent_classification(question):
        classification = await classify_intent(
            question, providers.guardrail, model=providers.guardrail_model
        )
        intent_label = classification.intent
        l2_trace = GuardrailL2Trace(
            status="run", intent=intent_label, reason=classification.reason
        )

        if intent_label == "MEDICAL_REFUSE":
            log.info("rag.intent_refused", intent=intent_label)
            return RAGResponse(
                answer=RESPONSE_MEDICAL_REFUSE,
                in_scope=False, sources=[], intent=intent_label,
                trace=PipelineTrace(guardrail_l1=l1_trace, guardrail_l2=l2_trace),
            )
        if intent_label == "EATING_RISK":
            log.info("rag.intent_refused", intent=intent_label)
            return RAGResponse(
                answer=RESPONSE_EATING_RISK,
                in_scope=False, sources=[], intent=intent_label,
                trace=PipelineTrace(guardrail_l1=l1_trace, guardrail_l2=l2_trace),
            )
        if intent_label == "OUT_OF_SCOPE":
            log.info("rag.intent_refused", intent=intent_label)
            return RAGResponse(
                answer=RESPONSE_OUT_OF_SCOPE,
                in_scope=False, sources=[],
                trace=PipelineTrace(guardrail_l1=l1_trace, guardrail_l2=l2_trace),
            )
        if intent_label == "BORDERLINE":
            was_borderline = True
    else:
        intent_label = None
        l2_trace = GuardrailL2Trace(status="skipped")

    # ── Query processing ──────────────────────────────────────────────────────
    query_type, sub_questions = await process_query(
        question,
        providers.classifier,
        classifier_model=providers.classifier_model,
        rewrite_model=providers.rewrite_model,
        rewrite_provider=providers.rewrite,
    )
    log.info("rag.query_processed", query_type=query_type, num_sub_questions=len(sub_questions))
    qp_trace = QueryProcessorTrace(query_type=query_type, sub_questions=sub_questions)

    # ── Retrieval ─────────────────────────────────────────────────────────────
    results_per_query, merged = await retrieve(
        sub_questions, query_type, providers.embedder, qdrant,
        max_sources=payload.max_sources,
    )
    retrieval_trace = RetrievalTrace(
        results_per_query=[len(r) for r in results_per_query],
        total_merged=len(merged),
    )

    if not merged:
        log.info("rag.no_results", query_type=query_type)
        return RAGResponse(
            answer=OUT_OF_SCOPE_MESSAGE,
            in_scope=False, sources=[], intent=query_type,
            trace=PipelineTrace(
                guardrail_l1=l1_trace, guardrail_l2=l2_trace,
                query_processor=qp_trace, retrieval=retrieval_trace,
            ),
        )

    # ── Context assembly ──────────────────────────────────────────────────────
    context, used_chunks, assembly_strategy, conflict_count = await assemble_context(
        results_per_query, sub_questions, query_type,
        provider=providers.conflict,
        conflict_model=providers.conflict_model,
    )
    context_trace = ContextTrace(
        strategy=assembly_strategy,
        conflict_count=conflict_count,
        chunks_used=len(used_chunks),
    )

    # ── Generation ────────────────────────────────────────────────────────────
    llm_response = await generate(
        question, context, query_type,
        providers.generation,
        model=providers.generation_model,
    )
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
        trace    = PipelineTrace(
            guardrail_l1=l1_trace,
            guardrail_l2=l2_trace,
            query_processor=qp_trace,
            retrieval=retrieval_trace,
            context=context_trace,
        ),
    )


# ── Streaming endpoint ────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/query/stream")
async def query_rag_stream(
    payload: RAGQuery,
    providers: PipelineProviders = Depends(get_pipeline_providers),
    qdrant: QdrantVectorDB = Depends(get_qdrant),
) -> StreamingResponse:

    async def _events():  # type: ignore[return]
        try:
            question = payload.question

            # ── L1: hard-block ────────────────────────────────────────────────
            block_reason = hard_block_check(question)
            if block_reason:
                log.info("rag.stream.hard_block", reason=block_reason)
                trace = PipelineTrace(
                    guardrail_l1=GuardrailL1Trace(status="blocked", block_reason=block_reason)
                )
                yield _sse({"type": "done", "answer": RESPONSE_OUT_OF_SCOPE, "in_scope": False,
                            "sources": [], "intent": None, "model": None, "usage": None,
                            "trace": trace.model_dump()})
                return

            l1_trace = GuardrailL1Trace(status="passed")

            # ── L2: intent classifier ─────────────────────────────────────────
            was_borderline = False
            if needs_intent_classification(question):
                classification = await classify_intent(
                    question, providers.guardrail, model=providers.guardrail_model
                )
                intent_label = classification.intent
                l2_trace = GuardrailL2Trace(
                    status="run", intent=intent_label, reason=classification.reason
                )

                refuse_map = {
                    "MEDICAL_REFUSE": RESPONSE_MEDICAL_REFUSE,
                    "EATING_RISK": RESPONSE_EATING_RISK,
                    "OUT_OF_SCOPE": RESPONSE_OUT_OF_SCOPE,
                }
                if intent_label in refuse_map:
                    log.info("rag.stream.intent_refused", intent=intent_label)
                    trace = PipelineTrace(guardrail_l1=l1_trace, guardrail_l2=l2_trace)
                    yield _sse({"type": "done", "answer": refuse_map[intent_label], "in_scope": False,
                                "sources": [], "intent": intent_label, "model": None, "usage": None,
                                "trace": trace.model_dump()})
                    return
                if intent_label == "BORDERLINE":
                    was_borderline = True
            else:
                intent_label = None
                l2_trace = GuardrailL2Trace(status="skipped")

            # ── Query processing ──────────────────────────────────────────────
            query_type, sub_questions = await process_query(
                question,
                providers.classifier,
                classifier_model=providers.classifier_model,
                rewrite_model=providers.rewrite_model,
                rewrite_provider=providers.rewrite,
            )
            qp_trace = QueryProcessorTrace(query_type=query_type, sub_questions=sub_questions)

            # ── Retrieval ─────────────────────────────────────────────────────
            results_per_query, merged = await retrieve(
                sub_questions, query_type, providers.embedder, qdrant,
                max_sources=payload.max_sources,
            )
            retrieval_trace = RetrievalTrace(
                results_per_query=[len(r) for r in results_per_query],
                total_merged=len(merged),
            )

            if not merged:
                trace = PipelineTrace(
                    guardrail_l1=l1_trace, guardrail_l2=l2_trace,
                    query_processor=qp_trace, retrieval=retrieval_trace,
                )
                yield _sse({"type": "done", "answer": OUT_OF_SCOPE_MESSAGE, "in_scope": False,
                            "sources": [], "intent": query_type, "model": None, "usage": None,
                            "trace": trace.model_dump()})
                return

            # ── Context assembly ──────────────────────────────────────────────
            context, used_chunks, assembly_strategy, conflict_count = await assemble_context(
                results_per_query, sub_questions, query_type,
                provider=providers.conflict,
                conflict_model=providers.conflict_model,
            )
            context_trace = ContextTrace(
                strategy=assembly_strategy,
                conflict_count=conflict_count,
                chunks_used=len(used_chunks),
            )

            # ── Generation (token stream) ─────────────────────────────────────
            system = GENERATION_STREAM_SYSTEM
            if query_type in ("COMPLEX", "COMPARISON"):
                system += SYNTHESIS_INSTRUCTION
            full_system = system + "\n\n" + context

            collected: list[str] = []
            async for token in providers.generation.stream(  # type: ignore[attr-defined]
                messages=[LLMMessage(role="user", content=question)],
                system=full_system,
                max_tokens=512,
                temperature=0.2,
                model=providers.generation_model,
            ):
                collected.append(token)
                yield _sse({"type": "token", "content": token})

            # ── Finalise ──────────────────────────────────────────────────────
            answer = "".join(collected)
            if was_borderline:
                answer += BORDERLINE_DISCLAIMER

            sources = [
                RAGSource(
                    doc_title=c.doc_title,
                    section_title=c.section_title,
                    source_file=c.source_file,
                    score=c.score,
                    excerpt=c.text[:200] + "...",
                )
                for c in used_chunks
            ]

            trace = PipelineTrace(
                guardrail_l1=l1_trace,
                guardrail_l2=l2_trace,
                query_processor=qp_trace,
                retrieval=retrieval_trace,
                context=context_trace,
            )
            yield _sse({
                "type": "done",
                "answer": answer,
                "in_scope": True,
                "sources": [s.model_dump() for s in sources],
                "intent": query_type,
                "model": providers.generation_model,
                "usage": None,
                "trace": trace.model_dump(),
            })

        except Exception:
            log.exception("rag.stream.error")
            yield _sse({"type": "error", "message": "An error occurred while generating the response."})

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
