from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any

import structlog

from app.agent.roster import ATHLETE_ROSTER, find_athlete
from app.llm.base import ToolCall

log = structlog.get_logger(__name__)

MAX_TOOL_RESULT_CHARS = 4_000


def _trim(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[: MAX_TOOL_RESULT_CHARS] + "\n[... result trimmed to 4 000 chars]"


# ── Tool implementations ───────────────────────────────────────────────────────

async def tool_rag_search(query: str) -> str:
    from functools import lru_cache

    from app.core.config import settings
    from app.llm.factory import PipelineProviders
    from app.rag.query_processor import process_query
    from app.rag.retriever import assemble_context, retrieve
    from app.vectordb.qdrant import QdrantVectorDB

    @lru_cache(maxsize=1)
    def _qdrant() -> QdrantVectorDB:
        return QdrantVectorDB.from_url(
            url=settings.qdrant_url,
            collection_name=settings.qdrant_collection_knowledge,
            api_key=(
                settings.qdrant_api_key.get_secret_value()
                if settings.qdrant_api_key
                else None
            ),
        )

    providers = PipelineProviders()
    qdrant = _qdrant()

    query_type, sub_questions = await process_query(
        query,
        providers.classifier,
        classifier_model=providers.classifier_model,
        rewrite_model=providers.rewrite_model,
        rewrite_provider=providers.rewrite,
    )

    results_per_query, merged = await retrieve(
        sub_questions, query_type, providers.embedder, qdrant, max_sources=5
    )

    if not merged:
        return "NO_RESULTS: The knowledge base does not contain relevant information for this query."

    context_str, used_chunks, _strategy, _conflicts = await assemble_context(
        results_per_query,
        sub_questions,
        query_type,
        provider=providers.conflict,
        conflict_model=providers.conflict_model,
    )

    if not used_chunks:
        return "NO_RESULTS: The knowledge base does not contain relevant information for this query."

    lines = [f'=== KNOWLEDGE BASE ===\nQuery: "{query}"\n']
    for i, chunk in enumerate(used_chunks, start=1):
        lines.append(f"[{i}] {chunk.source_file}\n    {chunk.text[:600]}")

    return _trim("\n\n".join(lines))


async def tool_analyze_history(
    athlete: str,
    question: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Analyse a named athlete's workout history. Athlete name is resolved server-side."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.workout import WorkoutRepository
    from app.schemas.workout import WorkoutAnalysisRequest
    from app.services.workout import WorkoutPipelineProviders, WorkoutService

    # Resolve athlete name → user_id
    a = find_athlete(athlete)
    if a is None:
        available = ", ".join(x.name for x in ATHLETE_ROSTER)
        return (
            f"ERROR: Unknown athlete '{athlete}'. "
            f"Available athletes in the roster: {available}. "
            "Please use one of those names exactly."
        )

    date_from_obj: date | None = date.fromisoformat(date_from) if date_from else None
    date_to_obj: date | None = date.fromisoformat(date_to) if date_to else None

    request = WorkoutAnalysisRequest(
        question=question,
        date_from=date_from_obj,
        date_to=date_to_obj,
    )

    async with AsyncSessionLocal() as session:
        repo = WorkoutRepository(session)
        providers = WorkoutPipelineProviders()
        service = WorkoutService(repo, providers)
        response = await service.analyse(a.user_id, request)

    return _trim(_format_analysis_result(a.name, response))


def _format_analysis_result(athlete_name: str, response: Any) -> str:
    summary = response.data_summary

    if summary.insufficient_data:
        date_from = summary.date_range.get("from", "?")
        date_to = summary.date_range.get("to", "?")
        return (
            f"=== WORKOUT ANALYSIS: {athlete_name} ===\n"
            f"INSUFFICIENT DATA: Only {summary.sessions_analysed} session(s) found "
            f"in {date_from} → {date_to}.\n"
            "Log at least 2 sessions before requesting an analysis."
        )

    date_from = summary.date_range.get("from", "?")
    date_to = summary.date_range.get("to", "?")
    lines = [
        f"=== WORKOUT ANALYSIS: {athlete_name} ===",
        f"Period: {date_from} → {date_to}  "
        f"|  Sessions: {summary.sessions_analysed}  "
        f"|  Exercises: {summary.exercises_found}",
        "",
    ]
    if summary.muscle_groups_found:
        lines.append(f"MUSCLE GROUPS TRAINED: {', '.join(summary.muscle_groups_found)}")
        lines.append("")
    if summary.deload_weeks_detected:
        lines.append(f"DELOAD WEEKS DETECTED: {summary.deload_weeks_detected}")
        lines.append("")
    else:
        lines.append("DELOAD WEEKS: None detected in the selected period")
        lines.append("")
    lines.append("ANALYSIS")
    lines.append(response.answer)
    return "\n".join(lines)


# ── Tool registry & dispatch ───────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {
    "rag_search": tool_rag_search,
    "analyze_history": tool_analyze_history,
}


async def dispatch_tool(tool_call: ToolCall) -> str:
    fn = TOOL_REGISTRY.get(tool_call.name)
    if fn is None:
        return f"ERROR: Unknown tool '{tool_call.name}'"
    try:
        return await fn(**tool_call.input)
    except Exception as exc:
        log.warning(
            "agent.tool.error",
            tool=tool_call.name,
            err_type=type(exc).__name__,
        )
        return f"ERROR: {type(exc).__name__}: {exc}"


async def execute_tools(tool_calls: list[ToolCall]) -> list[tuple[str, str]]:
    tasks = [dispatch_tool(tc) for tc in tool_calls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        (
            tc.name,
            r if isinstance(r, str) else f"ERROR: {type(r).__name__}: {r}",
        )
        for tc, r in zip(tool_calls, results)
    ]
