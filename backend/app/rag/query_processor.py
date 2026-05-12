from __future__ import annotations

import json
import re
from typing import Literal

from app.llm.base import BaseLLMProvider, LLMMessage
from app.prompts.query_classifier import QUERY_CLASSIFIER_SYSTEM
from app.prompts.query_rewrite import QUERY_DECOMPOSE_SYSTEM, QUERY_REWRITE_SYSTEM

QueryType = Literal["SIMPLE", "COMPLEX", "COMPARISON"]

# ── Heuristic patterns ────────────────────────────────────────────────────────

_COMPARISON_SIGNALS = re.compile(
    r"\b(vs\.?|versus|compare|comparison|difference between|better than|which is better|"
    r"or\b.{3,40}\bor\b)\b",
    re.IGNORECASE,
)
_COMPLEXITY_SIGNALS = re.compile(
    r"\b(and (also|how|what|when|why)|both .{3,30} and|additionally|as well as|"
    r"at the same time|while also)\b",
    re.IGNORECASE,
)

# ── System prompts ────────────────────────────────────────────────────────────

QUERY_CLASSIFIER_SYSTEM_PROMPT = QUERY_CLASSIFIER_SYSTEM
QUERY_REWRITE_SYSTEM_PROMPT = QUERY_REWRITE_SYSTEM
QUERY_DECOMPOSE_SYSTEM_PROMPT = QUERY_DECOMPOSE_SYSTEM


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json_block(raw: str) -> str:
    m = re.search(r"\{.*?\}", raw, re.DOTALL)
    return m.group(0) if m else raw


# ── Public API ────────────────────────────────────────────────────────────────

def classify_query_heuristic(question: str) -> QueryType | None:
    """Fast heuristic pre-filter. Returns None when LLM classification is needed."""
    if _COMPARISON_SIGNALS.search(question):
        return "COMPARISON"
    if len(question) > 120 and _COMPLEXITY_SIGNALS.search(question):
        return "COMPLEX"
    if len(question) <= 80:
        return "SIMPLE"
    return None


async def classify_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> QueryType:
    fast = classify_query_heuristic(question)
    if fast is not None:
        return fast
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_CLASSIFIER_SYSTEM_PROMPT,
        max_tokens=60,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json_block(resp.content))
        t = data.get("type", "SIMPLE")
        return t if t in ("SIMPLE", "COMPLEX", "COMPARISON") else "SIMPLE"
    except Exception:
        return "SIMPLE"


async def rewrite_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> str:
    if len(question) > 80:
        return question
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_REWRITE_SYSTEM_PROMPT,
        max_tokens=80,
        temperature=0.0,
        model=model,
    )
    rewritten = resp.content.strip().strip('"')
    if not rewritten or len(rewritten) > 300:
        return question
    return rewritten


async def decompose_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> list[str]:
    resp = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=QUERY_DECOMPOSE_SYSTEM_PROMPT,
        max_tokens=200,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json_block(resp.content))
        subs = [s.strip() for s in data.get("sub_questions", []) if s.strip()]
        if 1 <= len(subs) <= 3:
            return subs
    except Exception:
        pass
    return [question]


async def process_query(
    question: str,
    provider: BaseLLMProvider,
    *,
    classifier_model: str | None = None,
    rewrite_provider: BaseLLMProvider | None = None,
    rewrite_model: str | None = None,
) -> tuple[QueryType, list[str]]:
    """
    Classify then rewrite or decompose.
    SIMPLE       → (SIMPLE, [rewritten_question])
    COMPLEX      → (COMPLEX, [sub_q1, sub_q2, ...])
    COMPARISON   → (COMPARISON, [sub_q1, sub_q2, ...])

    rewrite_provider: separate provider for rewrite/decompose steps (falls back
    to the classifier provider when None).
    """
    query_type = await classify_query(question, provider, model=classifier_model)
    rw = rewrite_provider or provider

    if query_type == "SIMPLE":
        rewritten = await rewrite_query(question, rw, model=rewrite_model)
        return query_type, [rewritten]

    sub_questions = await decompose_query(question, rw, model=rewrite_model)
    return query_type, sub_questions
