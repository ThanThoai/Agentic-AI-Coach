from __future__ import annotations

import json
import re
from typing import Literal

from app.llm.base import BaseLLMProvider, LLMMessage

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

QUERY_CLASSIFIER_SYSTEM_PROMPT = """\
You are a fitness question classifier. Classify the query as exactly one of:

  SIMPLE      — Single focused question answerable from one topic area.
                A question is SIMPLE when it asks about one concept, one technique,
                or one programming variable.

  COMPLEX     — Multi-part question requiring information from more than one
                distinct topic. Look for conjunctions that join two independent
                sub-questions (e.g. "... and how ...", "... as well as ...").

  COMPARISON  — Asks to evaluate, rank, or contrast two or more options.
                Look for "vs", "versus", "better than", "or ... or", "which".

---

Examples:

Query: "How many sets per week should I do for chest hypertrophy?"
{"type": "SIMPLE", "reason": "Single focused question about volume for one muscle group"}

Query: "What does RPE mean in strength training?"
{"type": "SIMPLE", "reason": "Definitional question about a single concept"}

Query: "Should I do cardio on rest days?"
{"type": "SIMPLE", "reason": "Single programming question, no competing sub-topics"}

Query: "How should I structure my PPL split and what intensity should I train at for hypertrophy?"
{"type": "COMPLEX", "reason": "Two independent sub-topics: split structure and training intensity"}

Query: "What should my macros be and how should I time my meals around training?"
{"type": "COMPLEX", "reason": "Macro targets and meal timing are separate retrieval targets"}

Query: "How do I fix my squat depth and what accessories can help bring it up?"
{"type": "COMPLEX", "reason": "Technique correction and accessory programming require different knowledge"}

Query: "Is PPL or Upper/Lower better for an intermediate lifter building muscle?"
{"type": "COMPARISON", "reason": "Contrasting two split options for the same goal"}

Query: "Creatine monohydrate vs HMB — which is more effective for muscle gain?"
{"type": "COMPARISON", "reason": "Direct head-to-head comparison of two supplements"}

Query: "Should I do 5x5 or 3x10 for building strength?"
{"type": "COMPARISON", "reason": "Evaluating two rep-range protocols against each other"}

---

Return JSON only: {"type": "SIMPLE" | "COMPLEX" | "COMPARISON", "reason": "<one sentence>"}

Query: {question}"""

QUERY_REWRITE_SYSTEM_PROMPT = """\
You are a search query optimizer for a fitness coaching knowledge base.
Rewrite the user's question into a richer search query:
- Expand abbreviations (PPL → Push Pull Legs, OHP → overhead press, RDL → Romanian deadlift)
- Add fitness synonyms and related terms (hypertrophy → muscle growth, volume)
- Make implicit context explicit ("bench press" → "bench press barbell technique form chest")
- Keep the rewrite under 150 characters

Return only the rewritten query string, no explanation, no quotes.

---

Examples:

Question: "OHP form tips"
overhead press barbell technique form shoulder press mechanics cues proper positioning stability

Question: "DOMS after leg day"
delayed onset muscle soreness DOMS causes treatment recovery muscle pain after workout squat legs

Question: "best PPL"
Push Pull Legs PPL workout split program structure frequency hypertrophy strength intermediate

Question: "progressive overload bench"
progressive overload bench press barbell strength programming adding weight reps sets progression method

Question: "chest won't grow"
chest pectoral muscle growth plateau hypertrophy technique volume progressive overload exercises stagnation

Question: "training frequency"
optimal training frequency sessions per week muscle group hypertrophy recovery stimulus adaptation

Question: "RDL how to"
Romanian deadlift RDL technique form hip hinge hamstring stretch posterior chain barbell execution cues

---

Question: {question}"""

QUERY_DECOMPOSE_SYSTEM_PROMPT = """\
You are a query decomposer for a fitness coaching knowledge base.
Break the user's question into 2-3 focused sub-questions that can each be
answered independently from the knowledge base.

Rules:
- Each sub-question must be independently answerable
- Expand abbreviations in every sub-question
- For COMPARISON questions: one sub-question per option being compared
- For COMPLEX questions: one sub-question per distinct topic or concern
- Do not produce more than 3 sub-questions

---

Examples:

Question: "How should I structure my PPL split and what intensity should I train at for hypertrophy?"
{"sub_questions": [
  "Push Pull Legs PPL workout split structure sessions per week frequency hypertrophy",
  "training intensity percentage 1RM RPE range optimal muscle growth hypertrophy"
]}

Question: "What should my macros be and how should I time my meals around training?"
{"sub_questions": [
  "macronutrients protein carbohydrate fat ratio targets muscle building body composition",
  "meal timing pre-workout post-workout nutrition performance recovery"
]}

Question: "How do I fix my squat depth and what accessory exercises can help improve it?"
{"sub_questions": [
  "squat depth improvement ankle hip mobility flexibility technique cues drills",
  "accessory exercises improve squat depth goblet squat box squat pause squat"
]}

Question: "Is free weights or machines better for building muscle?"
{"sub_questions": [
  "free weights barbell dumbbell muscle hypertrophy advantages compound movement stability",
  "resistance machines muscle hypertrophy advantages isolation stability range of motion"
]}

Question: "Should I use creatine or protein powder as my first supplement?"
{"sub_questions": [
  "creatine monohydrate benefits muscle building strength performance beginner supplement",
  "protein powder whey supplement muscle synthesis recovery daily protein intake"
]}

Question: "Which is better for fat loss and muscle retention — HIIT or steady state cardio?"
{"sub_questions": [
  "HIIT high intensity interval training fat loss muscle retention caloric expenditure",
  "steady state cardio LISS fat loss muscle preservation aerobic base caloric expenditure"
]}

---

Return JSON only: {"sub_questions": ["...", "...", "..."]}

Question: {question}"""


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
    rewrite_model: str | None = None,
) -> tuple[QueryType, list[str]]:
    """
    Classify then rewrite or decompose.
    SIMPLE       → (SIMPLE, [rewritten_question])
    COMPLEX      → (COMPLEX, [sub_q1, sub_q2, ...])
    COMPARISON   → (COMPARISON, [sub_q1, sub_q2, ...])
    """
    query_type = await classify_query(question, provider, model=classifier_model)

    if query_type == "SIMPLE":
        rewritten = await rewrite_query(question, provider, model=rewrite_model)
        return query_type, [rewritten]

    sub_questions = await decompose_query(question, provider, model=rewrite_model)
    return query_type, sub_questions
