"""Evaluation harness CLI.

Usage:
    cd backend
    uv run python -m tests.eval.runner
    uv run python -m tests.eval.runner --category rag
    uv run python -m tests.eval.runner --output-dir /tmp/eval_results
    uv run python -m tests.eval.runner --debug          # show raw model responses
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure backend/ is on sys.path when run as __main__
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.llm.factory import PipelineProviders
from app.rag.schemas import RAGResponse
from app.schemas.agent import AgentResponse
from app.schemas.workout import WorkoutAnalysisResponse
from app.services.workout import WorkoutPipelineProviders
from app.vectordb.qdrant import QdrantVectorDB

from .metrics.faithfulness import score_faithfulness
from .metrics.helpfulness import score_helpfulness
from .metrics.judge_panel import JuryVerdict
from .metrics.rule_based import (
    check_citation_presence,
    check_data_values_referenced,
    check_guardrail_blocked,
    check_intent_label,
    check_no_system_prompt_leaked,
    check_out_of_scope_message,
)
from .report import write_json, write_report, print_summary
from .runners.agent_runner import run_agent_case
from .runners.rag_runner import run_rag_case
from .runners.workout_runner import run_workout_case
from .schemas import CaseResult, TestCase

_DATASET_DIR = _HERE / "dataset"


def _verdict_dict(v: JuryVerdict) -> dict[str, Any]:
    """Serialize a JuryVerdict to a JSON-safe dict for storage."""
    return {
        "scores": v.scores,
        "reasons": v.reasons,
        "mean": round(v.mean, 3),
        "std_dev": round(v.std_dev, 3),
        "min": v.min_score,
        "max": v.max_score,
        "normalized": round(v.normalized, 3),
        "disputed": v.disputed,
        "confidence": round(v.confidence, 3),
        "passed": v.passed,
    }


def load_testset(category: str) -> list[TestCase]:
    file_map = {
        "rag": "rag_testset.json",
        "workout": "workout_testset.json",
        "agent": "agent_testset.json",
        "adversarial": "adversarial_testset.json",
    }
    files = [file_map[category]] if category != "all" else list(file_map.values())
    cases: list[TestCase] = []
    for fname in files:
        path = _DATASET_DIR / fname
        raw = json.loads(path.read_text())
        for item in raw:
            cases.append(TestCase(**{
                k: v for k, v in item.items()
                if k in TestCase.__dataclass_fields__
            }))
    return cases


async def _score_rag_case(
    case: TestCase,
    response: RAGResponse,
    latency_ms: int,
) -> CaseResult:
    failure_reasons: list[str] = []
    answer = response.answer
    is_blocked = not response.in_scope

    # M1 — Faithfulness (only when there are sources)
    faithfulness_score = None
    faithfulness_disputed = None
    faithfulness_verdict_data = None
    if not is_blocked and response.sources:
        excerpts = [s.excerpt for s in response.sources]
        fv = await score_faithfulness(case.question, answer, excerpts)
        faithfulness_score = fv.normalized
        faithfulness_disputed = fv.disputed
        faithfulness_verdict_data = _verdict_dict(fv)
        if faithfulness_score < settings.eval_pass_threshold:
            failure_reasons.append(
                f"faithfulness={faithfulness_score:.2f} < {settings.eval_pass_threshold}"
            )

    # M2 — Helpfulness (only in-scope answers)
    helpfulness_score = None
    helpfulness_disputed = None
    helpfulness_verdict_data = None
    if not is_blocked:
        hv = await score_helpfulness(case.question, answer, "athlete")
        helpfulness_score = hv.normalized
        helpfulness_disputed = hv.disputed
        helpfulness_verdict_data = _verdict_dict(hv)
        if helpfulness_score < settings.eval_pass_threshold:
            failure_reasons.append(
                f"helpfulness={helpfulness_score:.2f} < {settings.eval_pass_threshold}"
            )

    # M3 — Citation presence (in-scope answers only)
    citation_present = None
    if not is_blocked and case.pass_criteria.get("citation_present", True):
        citation_present = check_citation_presence(answer)
        if not citation_present:
            failure_reasons.append("no [n] citation marker in answer")
    elif is_blocked:
        citation_present = None

    # M5 — Guardrail (for rag-10 out-of-scope test)
    guardrail_effective = None
    if not case.pass_criteria.get("in_scope", True):
        expected_blocked = not case.pass_criteria.get("in_scope", True)
        actual_blocked = is_blocked
        guardrail_effective = (expected_blocked == actual_blocked)
        if case.pass_criteria.get("out_of_scope_message_present"):
            has_msg = check_out_of_scope_message(answer)
            if not has_msg:
                failure_reasons.append("out-of-scope message not present in answer")
                guardrail_effective = False

    return CaseResult(
        case_id=case.id,
        category=case.category,
        question=case.question,
        actual_answer=answer,
        actual_metadata={
            "in_scope": response.in_scope,
            "sources_count": len(response.sources),
            "model": response.model,
            "trace": response.trace.model_dump() if response.trace else None,
        },
        faithfulness_score=faithfulness_score,
        faithfulness_disputed=faithfulness_disputed,
        helpfulness_score=helpfulness_score,
        helpfulness_disputed=helpfulness_disputed,
        citation_present=citation_present,
        data_values_referenced=None,
        guardrail_effective=guardrail_effective,
        overall_pass=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
        faithfulness_verdict=faithfulness_verdict_data,
        helpfulness_verdict=helpfulness_verdict_data,
        latency_ms=latency_ms,
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
    )


async def _score_adversarial_case(
    case: TestCase,
    response: RAGResponse,
    latency_ms: int,
) -> CaseResult:
    failure_reasons: list[str] = []
    answer = response.answer
    is_blocked = not response.in_scope

    guardrail_effective = check_guardrail_blocked(
        in_scope=response.in_scope,
        should_block=case.should_block,
    )
    if not guardrail_effective:
        expected = "blocked" if case.should_block else "passed"
        actual = "blocked" if is_blocked else "passed"
        failure_reasons.append(f"guardrail expected={expected} actual={actual}")

    # Check intent label for L2 cases
    actual_intent = None
    if response.trace and response.trace.guardrail_l2:
        actual_intent = response.trace.guardrail_l2.intent
    expected_intent = case.pass_criteria.get("intent_label")
    if expected_intent and not check_intent_label(actual_intent, expected_intent):
        failure_reasons.append(
            f"intent expected={expected_intent} actual={actual_intent}"
        )

    # For adv-05 (system prompt extraction), verify no leakage
    if case.pass_criteria.get("no_system_prompt_leaked"):
        if not check_no_system_prompt_leaked(answer):
            failure_reasons.append("system prompt content detected in answer")

    # For borderline case (adv-06), verify answer still provides guidance
    helpfulness_score = None
    helpfulness_disputed = None
    helpfulness_verdict_data = None
    if not is_blocked:
        hv = await score_helpfulness(case.question, answer, "athlete")
        helpfulness_score = hv.normalized
        helpfulness_disputed = hv.disputed
        helpfulness_verdict_data = _verdict_dict(hv)
        if helpfulness_score < settings.eval_pass_threshold:
            failure_reasons.append(
                f"helpfulness={helpfulness_score:.2f} — borderline case should still be helpful"
            )

    return CaseResult(
        case_id=case.id,
        category=case.category,
        question=case.question,
        actual_answer=answer,
        actual_metadata={
            "in_scope": response.in_scope,
            "intent": actual_intent,
            "should_block": case.should_block,
            "trace": response.trace.model_dump() if response.trace else None,
        },
        faithfulness_score=None,
        faithfulness_disputed=None,
        helpfulness_score=helpfulness_score,
        helpfulness_disputed=helpfulness_disputed,
        citation_present=None,
        data_values_referenced=None,
        guardrail_effective=guardrail_effective,
        overall_pass=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
        helpfulness_verdict=helpfulness_verdict_data,
        latency_ms=latency_ms,
        prompt_tokens=None,
        completion_tokens=None,
    )


async def _score_workout_case(
    case: TestCase,
    response: WorkoutAnalysisResponse,
    latency_ms: int,
) -> CaseResult:
    failure_reasons: list[str] = []
    answer = response.answer
    insufficient = response.data_summary.insufficient_data

    # If insufficient_data is expected, verify it
    expected_insufficient = case.pass_criteria.get("insufficient_data", False)
    if expected_insufficient and not insufficient:
        failure_reasons.append("expected insufficient_data=True but got False")
    if not expected_insufficient and insufficient:
        failure_reasons.append("unexpected insufficient_data=True")

    helpfulness_score = None
    helpfulness_disputed = None
    helpfulness_verdict_data = None
    if not insufficient:
        # M2 — Helpfulness
        hv = await score_helpfulness(case.question, answer, "coach")
        helpfulness_score = hv.normalized
        helpfulness_disputed = hv.disputed
        helpfulness_verdict_data = _verdict_dict(hv)
        if helpfulness_score < settings.eval_pass_threshold:
            failure_reasons.append(
                f"helpfulness={helpfulness_score:.2f} < {settings.eval_pass_threshold}"
            )

        # M4 — Data values referenced
        data_ok = check_data_values_referenced(answer)
        if case.pass_criteria.get("data_values_referenced") and not data_ok:
            failure_reasons.append("no numeric data values in answer")
    else:
        if case.pass_criteria.get("no_fabricated_analysis"):
            # Ensure the answer is the standard insufficient-data message, not a fake analysis
            has_fabrication = len(answer.split()) > 60 and check_data_values_referenced(answer)
            if has_fabrication:
                failure_reasons.append("possible fabricated analysis despite insufficient_data=True")

    data_values_referenced = check_data_values_referenced(answer) if not insufficient else None

    return CaseResult(
        case_id=case.id,
        category=case.category,
        question=case.question,
        actual_answer=answer,
        actual_metadata={
            "sessions_analysed": response.data_summary.sessions_analysed,
            "insufficient_data": insufficient,
            "date_range": response.data_summary.date_range,
            "model": response.model,
        },
        faithfulness_score=None,
        faithfulness_disputed=None,
        helpfulness_score=helpfulness_score,
        helpfulness_disputed=helpfulness_disputed,
        citation_present=None,
        data_values_referenced=data_values_referenced,
        guardrail_effective=None,
        overall_pass=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
        helpfulness_verdict=helpfulness_verdict_data,
        latency_ms=latency_ms,
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
    )


async def _score_agent_case(
    case: TestCase,
    response: AgentResponse,
    latency_ms: int,
) -> CaseResult:
    failure_reasons: list[str] = []
    answer = response.answer

    # Check tool usage match
    actual_tools = sorted(response.tools_used)
    expected_tools = sorted(case.expected_tools or [])
    if case.pass_criteria.get("tools_used_match"):
        # For duplicate tools (e.g. analyze_history × 2), compare as bags
        if actual_tools != expected_tools:
            failure_reasons.append(
                f"tools expected={expected_tools} actual={actual_tools}"
            )

    # Check iteration limit
    iterations_max = case.pass_criteria.get("iterations_max")
    if iterations_max and response.iterations > iterations_max:
        failure_reasons.append(
            f"iterations={response.iterations} > max={iterations_max}"
        )

    # M2 — Helpfulness
    hv = await score_helpfulness(case.question, answer, "coach")
    helpfulness_score = hv.normalized
    helpfulness_disputed = hv.disputed
    helpfulness_verdict_data = _verdict_dict(hv)
    if helpfulness_score < settings.eval_pass_threshold:
        failure_reasons.append(
            f"helpfulness={helpfulness_score:.2f} < {settings.eval_pass_threshold}"
        )

    # M4 — Data values referenced when analyze_history was used
    data_values_referenced = None
    if "analyze_history" in response.tools_used:
        data_values_referenced = check_data_values_referenced(answer)
        if case.pass_criteria.get("data_values_referenced") and not data_values_referenced:
            failure_reasons.append("no numeric data values in answer")

    # M1 — Faithfulness is not applicable for agent (no discrete sources list)

    return CaseResult(
        case_id=case.id,
        category=case.category,
        question=case.question,
        actual_answer=answer,
        actual_metadata={
            "tools_used": response.tools_used,
            "tool_calls": [tc.model_dump() for tc in response.tool_calls],
            "iterations": response.iterations,
        },
        faithfulness_score=None,
        faithfulness_disputed=None,
        helpfulness_score=helpfulness_score,
        helpfulness_disputed=helpfulness_disputed,
        citation_present=None,
        data_values_referenced=data_values_referenced,
        guardrail_effective=None,
        overall_pass=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
        helpfulness_verdict=helpfulness_verdict_data,
        latency_ms=latency_ms,
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
    )


async def run_all(
    cases: list[TestCase],
    rag_providers: PipelineProviders,
    qdrant: QdrantVectorDB,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    workout_providers = WorkoutPipelineProviders()

    async with AsyncSessionLocal() as session:
        for i, case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {case.id} ({case.category})...", end=" ", flush=True)
            try:
                if case.category == "rag":
                    rag_resp, latency_ms = await run_rag_case(case, rag_providers, qdrant)
                    result = await _score_rag_case(case, rag_resp, latency_ms)

                elif case.category == "adversarial":
                    adv_resp, latency_ms = await run_rag_case(case, rag_providers, qdrant)
                    result = await _score_adversarial_case(case, adv_resp, latency_ms)

                elif case.category == "workout":
                    wo_resp, latency_ms = await run_workout_case(case, session, workout_providers)
                    result = await _score_workout_case(case, wo_resp, latency_ms)

                elif case.category == "agent":
                    ag_resp, latency_ms = await run_agent_case(case)
                    result = await _score_agent_case(case, ag_resp, latency_ms)

                else:
                    raise ValueError(f"Unknown category: {case.category}")

                status = "PASS" if result.overall_pass else f"FAIL ({'; '.join(result.failure_reasons[:2])})"
                print(status)
                results.append(result)

            except Exception as exc:
                print(f"ERROR: {exc}")
                results.append(CaseResult(
                    case_id=case.id,
                    category=case.category,
                    question=case.question,
                    actual_answer="",
                    actual_metadata={"error": str(exc)},
                    faithfulness_score=None,
                    faithfulness_disputed=None,
                    helpfulness_score=None,
                    helpfulness_disputed=None,
                    citation_present=None,
                    data_values_referenced=None,
                    guardrail_effective=None,
                    overall_pass=False,
                    failure_reasons=[f"runner_error: {type(exc).__name__}: {exc}"],
                    latency_ms=0,
                ))

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Coach Agent evaluation harness")
    parser.add_argument(
        "--category",
        choices=["rag", "workout", "agent", "adversarial", "all"],
        default="all",
    )
    parser.add_argument("--output-dir", default="eval_results")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging for judge_panel (shows raw model responses)",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Always show WARNING+ for the judge panel; DEBUG only when --debug is set
    logging.getLogger("tests.eval.metrics.judge_panel").setLevel(log_level)

    print(f"Loading test cases (category={args.category})...")
    cases = load_testset(args.category)
    print(f"Loaded {len(cases)} cases.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Initialising providers...")
    rag_providers = PipelineProviders()
    qdrant = QdrantVectorDB.from_url(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
        collection_name=settings.qdrant_collection_knowledge,
    )

    print(f"\nRunning {len(cases)} evaluation cases:")
    results = await run_all(cases, rag_providers, qdrant)

    json_path = write_json(results, output_dir)
    md_path = write_report(results, output_dir)

    print(f"\nResults written to:\n  {json_path}\n  {md_path}")
    print()
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
