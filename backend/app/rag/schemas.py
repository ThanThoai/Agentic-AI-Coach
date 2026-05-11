from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RAGQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    max_sources: int = Field(default=5, ge=1, le=5)


class RAGSource(BaseModel):
    title: str
    section: str
    source_file: str
    score: float


class RAGResponse(BaseModel):
    answer: str
    in_scope: bool
    sources: list[RAGSource]
    intent: str | None = None
    model: str | None = None
    usage: dict | None = None
