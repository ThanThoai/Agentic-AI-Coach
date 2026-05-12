"""M1 — Faithfulness: Is the answer grounded in the retrieved context?

Uses a 3-judge panel (Sonnet + GPT-4o + Gemini-2.5-Pro) to score 1-5.
"""
from __future__ import annotations

from app.core.config import settings
from .judge_panel import JuryVerdict, run_jury

_SYSTEM = """\
You are an expert evaluator for a fitness coaching AI system.

Your task: assess whether an AI-generated answer is FAITHFUL to the provided source excerpts.

Faithfulness means every factual claim in the answer is supported by the context. The answer should not introduce information not present in the sources.

Score the answer on a scale of 1 to 5:
  5 - All claims are directly supported by the provided context
  4 - Most claims supported; minor unsupported detail that doesn't change meaning
  3 - Mix of supported and unsupported claims; some hallucination
  2 - Significant hallucination or contradiction with sources
  1 - Answer is largely unrelated to or contradicts the provided context

Respond ONLY with valid JSON: {"score": <integer 1-5>, "reason": "<one sentence explanation>"}
"""


def _user_message(question: str, answer: str, sources: list[str]) -> str:
    excerpts = "\n".join(f"[{i+1}] {s}" for i, s in enumerate(sources))
    return f"QUESTION: {question}\n\nSOURCE EXCERPTS:\n{excerpts}\n\nAI ANSWER:\n{answer}"


async def score_faithfulness(
    question: str,
    answer: str,
    sources: list[str],
) -> JuryVerdict:
    return await run_jury(
        system_prompt=_SYSTEM,
        user_message=_user_message(question, answer, sources),
        anthropic_model=settings.eval_faithfulness_model_anthropic,
        openai_model=settings.eval_faithfulness_model_openai,
        gemini_model=settings.eval_faithfulness_model_gemini,
        openrouter_anthropic=settings.openrouter_eval_faithfulness_anthropic,
        openrouter_openai=settings.openrouter_eval_faithfulness_openai,
        openrouter_gemini=settings.openrouter_eval_faithfulness_gemini,
    )
