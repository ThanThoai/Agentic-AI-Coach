from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestCase:
    id: str
    category: str          # "rag" | "workout" | "agent" | "adversarial"
    question: str
    expected_answer: str
    pass_criteria: dict[str, Any]

    # RAG
    query_type_expected: str | None = None

    # Workout
    athlete: str | None = None
    question_type_expected: str | None = None
    date_from_offset_days: int | None = None
    date_to_offset_days: int | None = None

    # Agent
    expected_tools: list[str] | None = None

    # Adversarial
    guardrail_layer_expected: str | None = None
    should_block: bool = False


@dataclass
class CaseResult:
    case_id: str
    category: str
    question: str

    # Raw pipeline response
    actual_answer: str
    actual_metadata: dict[str, Any]

    # LLM-judge verdicts — normalized score (None if metric not applicable)
    faithfulness_score: float | None
    faithfulness_disputed: bool | None
    helpfulness_score: float | None
    helpfulness_disputed: bool | None

    # Rule-based checks (None if not applicable)
    citation_present: bool | None       # M3 — RAG
    data_values_referenced: bool | None # M4 — Workout + Agent
    guardrail_effective: bool | None    # M5 — Adversarial

    # Overall
    overall_pass: bool

    # Default fields below ────────────────────────────────────────────────────

    failure_reasons: list[str] = field(default_factory=list)

    # Full JuryVerdict details — per-judge scores, reasons, confidence, etc.
    # Keyed "faithfulness" / "helpfulness"; None when metric not applicable.
    faithfulness_verdict: dict[str, Any] | None = None
    helpfulness_verdict: dict[str, Any] | None = None

    # Performance
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
