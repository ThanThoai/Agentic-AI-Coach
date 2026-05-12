from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import TokenUsage


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=5, max_length=1000)


class AgentResponse(BaseModel):
    answer: str
    tools_used: list[str]
    iterations: int
    usage: TokenUsage
