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
    "I don't have information on that topic in my knowledge base.\n\n"
    "I can help with:\n"
    "- Strength training principles (RPE, progressive overload, periodization)\n"
    "- Exercise technique and programming (training splits, deload weeks, 1RM)\n"
    "- Muscle recovery and training frequency\n"
    "- Nutrition fundamentals for performance\n\n"
    "Feel free to ask about any of those."
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

# Named medical conditions that always trigger L2 classification (do not hard-block at L1
# since L2 distinguishes informational queries from symptom-reporting queries).
MEDICAL_CONDITION_TERMS: list[str] = [
    # Spinal conditions
    r"herniated?\s+disc",
    r"bulging?\s+disc",
    r"slipped?\s+disc",
    r"\bscoliosis\b",
    r"spinal\s+stenosis",
    # Ligament / cartilage injuries
    r"\bACL\b",
    r"\bPCL\b",
    r"\bMCL\b",
    r"\bLCL\b",
    r"torn?\s+(ligament|meniscus|labrum|rotator)",
    r"ruptured?\s+(ligament|tendon|muscle)",
    r"labral?\s+tear",
    r"meniscus\s+(tear|damage|injury)",
    # Bone injuries
    r"stress\s+fracture",
    r"bone\s+fracture",
    r"\bfracture\b",
    # Chronic conditions
    r"\barthritis\b",
    r"\btendinitis\b|\btendonitis\b",
    r"\bbursitis\b",
    r"\bimpingement\b",
    r"plantar\s+fasciitis",
    r"shin\s+splints",
    r"rotator\s+cuff",
]

# Injury-report sentence patterns — broad heuristics that trigger L2 even when no specific
# condition term is found. L2 (the LLM classifier) makes the final SAFE vs MEDICAL_REFUSE
# determination; the cost of an extra LLM call is lower than missing a medical context.
INJURY_REPORT_PATTERNS: list[str] = [
    r"i\s+have\s+a?\s*\w+\s+(in|on|around)\s+(my\s+)?(back|knee|shoulder|hip|ankle|neck|spine|wrist|elbow)",
    r"i\s+(have|had|suffer|suffer from|got)\s+a?\s*(injury|condition|problem|issue|damage)\b",
    r"(my|the)\s+\w+\s+(hurts?|is\s+(injured|damaged|torn|inflamed|swollen|fractured))",
    r"(diagnosed|told)\s+(with|by)\s+(a\s+)?(doctor|physio|specialist|physician)",
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
    if any(re.search(p, q) for p in LAYER2_TRIGGER_PATTERNS):
        return True
    # Named medical conditions always trigger L2 regardless of other signals
    if any(re.search(p, question, re.IGNORECASE) for p in MEDICAL_CONDITION_TERMS):
        return True
    # Injury-report sentence patterns (broad; L2 makes the final call)
    if any(re.search(p, q) for p in INJURY_REPORT_PATTERNS):
        return True
    return False


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
    cleaned = raw.strip()
    # Strip markdown code fences so models that wrap JSON in ```json...``` still parse
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
    try:
        data = json.loads(cleaned)
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
