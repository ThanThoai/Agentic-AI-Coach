"""Post-generation faithfulness auditor (Change 1C).

After the RAG answer is generated, this module classifies each factual sentence as
SUPPORTED, INFERRED, or UNSUPPORTED against the retrieved source chunks. If the
unsupported fraction exceeds the threshold, the answer is regenerated with an
explicit constraint listing the unsupported claims to remove.

This runs as an inline step before the answer is returned. If the check itself fails
(LLM error, timeout, parse error), the original answer is returned unchanged and a
warning is logged — never blocks a response.
"""
from __future__ import annotations

import json
import re

import structlog

from app.llm.base import BaseLLMProvider, LLMMessage

log = structlog.get_logger(__name__)

UNSUPPORTED_FRACTION_THRESHOLD = 0.15

GROUNDING_PROMPT = """\
You are a faithfulness auditor for a fitness coaching assistant.

Given an answer and the source excerpts used to generate it, classify each sentence
in the answer as:
  SUPPORTED   — directly stated or closely paraphrased from a source chunk
  INFERRED    — reasonable inference from the sources (not fabricated)
  UNSUPPORTED — no supporting chunk; information came from outside the sources

SOURCE EXCERPTS:
{context}

ANSWER:
{answer}

Return JSON only:
{{"sentences": [{{"text": "...", "label": "SUPPORTED|INFERRED|UNSUPPORTED"}}]}}"""

REGENERATE_PROMPT = """\
You are a fitness coach assistant. Rewrite the answer below to remove all unsupported
claims. Use ONLY the information in the SOURCE EXCERPTS. Keep the supported content
intact and cite sources with [N].

SOURCE EXCERPTS:
{context}

ORIGINAL ANSWER (contains unsupported claims to remove):
{answer}

CLAIMS TO REMOVE (not found in sources):
{unsupported}

Return JSON: {{"answer": "...", "cited_indices": [1, 3]}}"""


class GroundingResult:
    def __init__(self, sentences: list[dict[str, str]]) -> None:
        self.sentences = sentences

    @property
    def unsupported_fraction(self) -> float:
        if not self.sentences:
            return 0.0
        unsupported = sum(1 for s in self.sentences if s.get("label") == "UNSUPPORTED")
        return unsupported / len(self.sentences)

    @property
    def unsupported_sentences(self) -> list[str]:
        return [s["text"] for s in self.sentences if s.get("label") == "UNSUPPORTED"]


def _extract_json(raw: str) -> str:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return m.group(0) if m else raw


async def check_grounding(
    answer: str,
    context: str,
    llm: BaseLLMProvider,
    *,
    model: str | None = None,
) -> GroundingResult:
    prompt = GROUNDING_PROMPT.format(context=context, answer=answer)
    response = await llm.complete(
        messages=[LLMMessage(role="user", content=prompt)],
        max_tokens=1024,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json(response.content))
        sentences: list[dict[str, str]] = data.get("sentences", [])
        return GroundingResult(sentences)
    except Exception:
        return GroundingResult([])


async def regenerate_with_strict_prompt(
    answer: str,
    context: str,
    unsupported: list[str],
    llm: BaseLLMProvider,
    *,
    model: str | None = None,
) -> str:
    unsupported_block = "\n".join(f"- {s}" for s in unsupported)
    prompt = REGENERATE_PROMPT.format(
        context=context, answer=answer, unsupported=unsupported_block
    )
    response = await llm.complete(
        messages=[LLMMessage(role="user", content=prompt)],
        max_tokens=350,
        temperature=0.0,
        model=model,
    )
    try:
        data = json.loads(_extract_json(response.content))
        return str(data.get("answer", answer))
    except Exception:
        return answer


async def enforce_grounding(
    answer: str,
    context: str,
    llm: BaseLLMProvider,
    *,
    model: str | None = None,
) -> str:
    """Check grounding and regenerate if unsupported fraction exceeds threshold.

    Returns the original answer unchanged if the check itself fails.
    """
    try:
        result = await check_grounding(answer, context, llm, model=model)
        log.info(
            "rag.grounding_check",
            unsupported_fraction=round(result.unsupported_fraction, 3),
            sentence_count=len(result.sentences),
        )
        if result.unsupported_fraction > UNSUPPORTED_FRACTION_THRESHOLD:
            log.info(
                "rag.grounding_regenerate",
                unsupported_count=len(result.unsupported_sentences),
            )
            return await regenerate_with_strict_prompt(
                answer, context, result.unsupported_sentences, llm, model=model
            )
        return answer
    except Exception:
        log.warning("rag.grounding_check.failed", exc_info=True)
        return answer
