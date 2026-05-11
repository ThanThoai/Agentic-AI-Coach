from __future__ import annotations

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


class RAGResponse(BaseModel):
    answer: str
    in_scope: bool
    sources: list[RAGSource]
    intent: str | None = None
    model: str | None = None
    usage: TokenUsage | None = None
