from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from app.llm.base import BaseLLMProvider, LLMMessage
from app.prompts.guardrail import INTENT_CLASSIFIER_SYSTEM

# ── Response strings ──────────────────────────────────────────────────────────

BORDERLINE_DISCLAIMER = (
    "\n\n💡 **Note:** If you experience significant or persistent discomfort, "
    "stop and consult a qualified physiotherapist or trainer before continuing."
)

RESPONSE_MEDICAL_REFUSE = (
    "This question involves a medical condition or injury that requires professional "
    "assessment. Please consult a qualified healthcare provider or physiotherapist "
    "who can evaluate your specific situation safely."
)

RESPONSE_EATING_RISK = (
    "This question goes beyond general fitness coaching into nutrition territory that "
    "a registered dietitian is best placed to handle. I'd recommend speaking with one "
    "who can build a safe, personalised plan for you."
)

RESPONSE_OUT_OF_SCOPE = (
    "I'm a fitness coaching assistant — I can help with training, exercise technique, "
    "programming, and sports nutrition. This question falls outside that scope."
)

OUT_OF_SCOPE_MESSAGE = (
    "I couldn't find relevant information in the fitness knowledge base for that question. "
    "Please ask something related to training, exercise technique, programming, or sports nutrition."
)

MEDICAL_DISCLAIMER = (
    "\n\n⚠️ This response touches on health or injury topics. "
    "Please consult a qualified healthcare professional before making "
    "decisions that affect your health."
)

# ── Layer 1 constants ─────────────────────────────────────────────────────────

HARD_BLOCK_PATTERNS: list[tuple[str, str]] = [
    # Non-fitness domains — high-confidence rejection
    (r"\b(weather|forecast|temperature|rain|sunny)\b", "weather query"),
    (r"\b(stock|crypto|bitcoin|investment|portfolio)\b", "finance query"),
    (r"\b(python|javascript|sql|code|programming|bug|debug)\b", "coding query"),
    (r"\b(recipe|cook|bake|ingredient|flour|sugar)\b", "cooking query"),
    (r"\b(news|politics|election|government|war)\b", "current events query"),
    # Prompt injection attempts
    (r"(ignore (previous|all) instructions|you are now|jailbreak)", "prompt injection"),
    (r"(system prompt|reveal your instructions|act as)", "prompt extraction"),
]

LAYER2_TRIGGER_PATTERNS: list[str] = [
    # Medical / injury signals → MEDICAL_REFUSE candidates
    r"\b(pain|ache|hurt|injury|injured|sprain|strain|herniat)\b",
    r"\b(surgery|operation|recovery|rehabilitation|rehab|post-op)\b",
    r"\b(doctor|physician|medical|diagnosis|prescription|diagnos)\b",
    r"\b(disease|condition|disorder|syndrome|chronic|diabetes|hypertension)\b",
    # Eating risk signals → EATING_RISK candidates
    r"\b(calories?|kcal).{0,20}(restrict|deficit|cut|fast|starv)\b",
    r"\b(lose|lost).{0,15}(kg|lbs|pound).{0,15}(week|month|fast|quick)\b",
    r"\b(not eating|skip(ping)? (meals?|food)|barely eat\w*)\b",
    # Mild risk signals → BORDERLINE candidates
    r"\b(sore|soreness|tight|stiff|discomfort)\b",
]

# ── Layer 2 constants ─────────────────────────────────────────────────────────

IntentLabel = Literal["SAFE", "BORDERLINE", "MEDICAL_REFUSE", "EATING_RISK", "OUT_OF_SCOPE"]

CLASSIFIER_SYSTEM_PROMPT = INTENT_CLASSIFIER_SYSTEM

# ── Layer 3 constants ─────────────────────────────────────────────────────────

MAX_ANSWER_LENGTH = 3000

MEDICAL_ADVICE_PATTERNS: list[str] = [
    r"\b(you (should|must|need to) (see|consult|visit) a (doctor|physician|specialist))\b",
    r"\b(diagnos(is|ed|e)|prescri(be|ption)|treat(ment|ing))\b",
    r"\b(surgery|surgical|medication|drug|dose|dosage)\b",
    r"\b(symptom[s]?|disease|disorder|condition)\b",
]

# ── Layer 2 schema ────────────────────────────────────────────────────────────


class ClassificationResult(BaseModel):
    intent: IntentLabel
    reason: str


# ── Layer 1 — Rule-based filter ───────────────────────────────────────────────


def hard_block_check(question: str) -> str | None:
    """Return block reason if the question matches a hard-block pattern, else None."""
    q = question.lower()
    for pattern, reason in HARD_BLOCK_PATTERNS:
        if re.search(pattern, q):
            return reason
    return None


def needs_intent_classification(question: str) -> bool:
    """Return True if the question contains signals that require Layer 2 classification."""
    q = question.lower()
    return any(re.search(p, q) for p in LAYER2_TRIGGER_PATTERNS)


# ── Layer 2 — LLM intent classifier ──────────────────────────────────────────


def _extract_json_block(raw: str) -> str:
    m = re.search(r"\{.*?\}", raw, re.DOTALL)
    return m.group(0) if m else raw


def _parse_classification(raw: str) -> ClassificationResult:
    """Parse classifier JSON; fall back to OUT_OF_SCOPE on any failure to fail safe."""
    try:
        return ClassificationResult.model_validate_json(_extract_json_block(raw).strip())
    except Exception:
        return ClassificationResult(intent="OUT_OF_SCOPE", reason="parse_error")


async def classify_intent(
    question: str,
    provider: BaseLLMProvider,
    *,
    model: str | None = None,
) -> ClassificationResult:
    """Call the LLM intent classifier and return a ClassificationResult."""
    response = await provider.complete(
        messages=[LLMMessage(role="user", content=question)],
        system=CLASSIFIER_SYSTEM_PROMPT,
        max_tokens=100,
        temperature=0.0,
        model=model,
    )
    return _parse_classification(response.content)


# ── Layer 3 — Output filter ───────────────────────────────────────────────────


def parse_llm_output(raw: str, num_chunks: int) -> tuple[str, list[int]]:
    """Parse the LLM's JSON response; fall back to raw text on parse failure."""
    try:
        data = json.loads(raw.strip())
        answer = str(data["answer"])
        indices = [int(i) for i in data.get("cited_indices", [])]
        return answer, indices
    except Exception:
        return raw.strip(), list(range(1, num_chunks + 1))


def contains_medical_advice(answer: str) -> bool:
    a = answer.lower()
    return any(re.search(p, a) for p in MEDICAL_ADVICE_PATTERNS)


def filter_output(
    raw: str,
    num_chunks: int,
    was_borderline: bool = False,
) -> tuple[str, list[int]]:
    """
    Apply all Layer 3 checks to raw LLM output.
    Returns (processed_answer, valid_cited_indices).
    """
    answer, cited_indices = parse_llm_output(raw, num_chunks)

    if len(answer) > MAX_ANSWER_LENGTH:
        answer = answer[:MAX_ANSWER_LENGTH] + "... [truncated]"

    cited_indices = [i for i in cited_indices if 1 <= i <= num_chunks]

    # Append medical disclaimer only when Layer 2 didn't already flag BORDERLINE
    if not was_borderline and contains_medical_advice(answer):
        answer += MEDICAL_DISCLAIMER

    return answer, cited_indices
