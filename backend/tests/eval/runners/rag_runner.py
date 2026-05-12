"""RAG pipeline runner for evaluation."""
from __future__ import annotations

import time

from app.llm.factory import PipelineProviders
from app.rag.guardrails import hard_block_check
from app.rag.schemas import RAGResponse
from app.vectordb.qdrant import QdrantVectorDB

from ..schemas import TestCase


async def run_rag_case(
    case: TestCase,
    providers: PipelineProviders,
    qdrant: QdrantVectorDB,
) -> tuple[RAGResponse, int]:
    """Run the full RAG pipeline for one test case; return (response, latency_ms)."""
    from app.api.v1.rag import query_rag
    from app.rag.schemas import RAGQuery

    t0 = time.monotonic()

    block_reason = hard_block_check(case.question)
    if block_reason:
        from app.rag.schemas import GuardrailL1Trace, PipelineTrace
        from app.rag.guardrails import RESPONSE_OUT_OF_SCOPE
        latency_ms = int((time.monotonic() - t0) * 1000)
        return RAGResponse(
            answer=RESPONSE_OUT_OF_SCOPE,
            in_scope=False,
            sources=[],
            trace=PipelineTrace(
                guardrail_l1=GuardrailL1Trace(status="blocked", block_reason=block_reason),
            ),
        ), latency_ms

    # Import the pipeline functions directly
    from app.rag.guardrails import (
        classify_intent,
        filter_output,
        needs_intent_classification,
        RESPONSE_MEDICAL_REFUSE,
        RESPONSE_EATING_RISK,
        RESPONSE_OUT_OF_SCOPE,
    )
    from app.rag.query_processor import process_query
    from app.rag.retriever import assemble_context, retrieve
    from app.rag.schemas import (
        GuardrailL1Trace,
        GuardrailL2Trace,
        QueryProcessorTrace,
        RetrievalTrace,
        ContextTrace,
        PipelineTrace,
    )
    from app.api.v1.rag import generate, _map_sources
    from app.rag.guardrails import OUT_OF_SCOPE_MESSAGE

    question = case.question
    l1_trace = GuardrailL1Trace(status="passed")
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
        refuse_map = {
            "MEDICAL_REFUSE": RESPONSE_MEDICAL_REFUSE,
            "EATING_RISK": RESPONSE_EATING_RISK,
            "OUT_OF_SCOPE": RESPONSE_OUT_OF_SCOPE,
        }
        if intent_label in refuse_map:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return RAGResponse(
                answer=refuse_map[intent_label],
                in_scope=False,
                sources=[],
                intent=intent_label,
                trace=PipelineTrace(guardrail_l1=l1_trace, guardrail_l2=l2_trace),
            ), latency_ms
        if intent_label == "BORDERLINE":
            was_borderline = True
    else:
        l2_trace = GuardrailL2Trace(status="skipped")

    query_type, sub_questions = await process_query(
        question,
        providers.classifier,
        classifier_model=providers.classifier_model,
        rewrite_model=providers.rewrite_model,
        rewrite_provider=providers.rewrite,
    )
    qp_trace = QueryProcessorTrace(query_type=query_type, sub_questions=sub_questions)

    results_per_query, merged = await retrieve(
        sub_questions, query_type, providers.embedder, qdrant,
    )
    retrieval_trace = RetrievalTrace(
        results_per_query=[len(r) for r in results_per_query],
        total_merged=len(merged),
    )

    if not merged:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return RAGResponse(
            answer=OUT_OF_SCOPE_MESSAGE,
            in_scope=False,
            sources=[],
            trace=PipelineTrace(
                guardrail_l1=l1_trace, guardrail_l2=l2_trace,
                query_processor=qp_trace, retrieval=retrieval_trace,
            ),
        ), latency_ms

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

    llm_response = await generate(
        question, context, query_type,
        providers.generation,
        model=providers.generation_model,
    )

    answer, cited_indices = filter_output(
        llm_response.content,
        num_chunks=len(used_chunks),
        was_borderline=was_borderline,
    )
    sources = _map_sources(used_chunks, cited_indices)

    latency_ms = int((time.monotonic() - t0) * 1000)
    return RAGResponse(
        answer=answer,
        in_scope=True,
        sources=sources,
        intent=query_type,
        model=llm_response.model,
        usage=llm_response.usage,
        trace=PipelineTrace(
            guardrail_l1=l1_trace,
            guardrail_l2=l2_trace,
            query_processor=qp_trace,
            retrieval=retrieval_trace,
            context=context_trace,
        ),
    ), latency_ms
