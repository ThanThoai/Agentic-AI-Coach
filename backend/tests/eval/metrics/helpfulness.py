"""M2 — Helpfulness: Is the answer useful, clear, and actionable?

Uses a 3-judge panel (Haiku + GPT-4o-mini + Gemini-2.0-Flash) to score 1-5.
"""
from __future__ import annotations

from app.core.config import settings
from .judge_panel import JuryVerdict, run_jury

_SYSTEM_ATHLETE = """\
You are an expert evaluator for a fitness coaching AI system.

Your task: assess the HELPFULNESS of an AI-generated answer for an ATHLETE.

A helpful answer for an athlete:
- Directly addresses the question asked
- Provides actionable, specific guidance (not vague platitudes)
- Uses appropriate tone (encouraging but evidence-based)
- Is appropriately concise — no padding or repetition
- Includes relevant numbers, progressions, or timeframes when applicable

Score the answer on a scale of 1 to 5:
  5 - Excellent: specific, actionable, directly answers the question, appropriate length
  4 - Good: answers the question well with minor gaps in specificity
  3 - Adequate: partially answers the question but lacks detail or clarity
  2 - Poor: vague, off-topic, or mostly unhelpful
  1 - Useless: does not address the question or is misleading

Respond ONLY with valid JSON: {"score": <integer 1-5>, "reason": "<one sentence explanation>"}
"""

_SYSTEM_COACH = """\
You are an expert evaluator for a fitness coaching AI system.

Your task: assess the HELPFULNESS of an AI-generated answer for a COACH.

A helpful answer for a coach:
- Provides professional-grade information the coach can apply to their athletes
- Includes evidence-based rationale (not just rules)
- Supports programming decisions with data or principles
- Is precise about volumes, intensities, and timeframes
- Respects the coach's expertise without over-simplifying

Score the answer on a scale of 1 to 5:
  5 - Excellent: professional, evidence-based, directly useful for coaching decisions
  4 - Good: useful for coaches with minor gaps
  3 - Adequate: partially useful but misses the coaching context
  2 - Poor: too basic, vague, or not applicable to coaching
  1 - Useless: does not address the coaching question

Respond ONLY with valid JSON: {"score": <integer 1-5>, "reason": "<one sentence explanation>"}
"""


def _user_message(question: str, answer: str) -> str:
    return f"QUESTION: {question}\n\nAI ANSWER:\n{answer}"


async def score_helpfulness(
    question: str,
    answer: str,
    context: str,  # "athlete" | "coach"
) -> JuryVerdict:
    system = _SYSTEM_COACH if context == "coach" else _SYSTEM_ATHLETE
    return await run_jury(
        system_prompt=system,
        user_message=_user_message(question, answer),
        anthropic_model=settings.eval_helpfulness_model_anthropic,
        openai_model=settings.eval_helpfulness_model_openai,
        gemini_model=settings.eval_helpfulness_model_gemini,
        openrouter_anthropic=settings.openrouter_eval_helpfulness_anthropic,
        openrouter_openai=settings.openrouter_eval_helpfulness_openai,
        openrouter_gemini=settings.openrouter_eval_helpfulness_gemini,
    )
