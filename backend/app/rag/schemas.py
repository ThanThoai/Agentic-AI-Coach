from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import TokenUsage


class RAGQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    max_sources: int = Field(default=5, ge=1, le=5)


class RAGSource(BaseModel):
    doc_title: str
    section_title: str
    source_file: str
    score: float
    excerpt: str


# ── Pipeline trace ────────────────────────────────────────────────────────────

class GuardrailL1Trace(BaseModel):
    status: Literal["passed", "blocked"]
    block_reason: str | None = None


class GuardrailL2Trace(BaseModel):
    status: Literal["run", "skipped"]
    intent: str | None = None
    reason: str | None = None


class QueryProcessorTrace(BaseModel):
    query_type: str
    sub_questions: list[str]


class RetrievalTrace(BaseModel):
    results_per_query: list[int]
    total_merged: int


class ContextTrace(BaseModel):
    strategy: str
    conflict_count: int
    chunks_used: int


class PipelineTrace(BaseModel):
    guardrail_l1: GuardrailL1Trace
    guardrail_l2: GuardrailL2Trace | None = None
    query_processor: QueryProcessorTrace | None = None
    retrieval: RetrievalTrace | None = None
    context: ContextTrace | None = None


class RAGResponse(BaseModel):
    answer: str
    in_scope: bool
    sources: list[RAGSource]
    intent: str | None = None
    model: str | None = None
    usage: TokenUsage | None = None
    trace: PipelineTrace | None = None
