"""Multi-LLM jury panel for M1 (faithfulness) and M2 (helpfulness)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from typing import cast

from app.core.config import LLMProvider, settings
from app.llm.base import BaseLLMProvider, LLMMessage
from app.llm.factory import build_provider

log = logging.getLogger(__name__)


@dataclass
class JuryVerdict:
    scores: dict[str, float]     # {"anthropic": 4.0, "openai": 4.0, "gemini": 3.0}
    reasons: dict[str, str]      # per-judge one-line reason
    mean: float
    std_dev: float
    min_score: float
    max_score: float
    normalized: float            # (mean - 1) / 4, maps 1-5 → 0-1
    disputed: bool               # True when max - min > dispute_threshold
    confidence: float            # 1 - (std_dev / 2), capped 0-1

    @property
    def passed(self) -> bool:
        return self.normalized >= settings.eval_pass_threshold


def _aggregate(
    raw_scores: dict[str, float],
    reasons: dict[str, str],
    dispute_threshold: float,
) -> JuryVerdict:
    values = list(raw_scores.values())
    mean = statistics.mean(values)
    std_dev = statistics.stdev(values) if len(values) > 1 else 0.0
    normalized = (mean - 1) / 4
    return JuryVerdict(
        scores=raw_scores,
        reasons=reasons,
        mean=mean,
        std_dev=std_dev,
        min_score=min(values),
        max_score=max(values),
        normalized=max(0.0, min(1.0, normalized)),
        disputed=(max(values) - min(values)) > dispute_threshold,
        confidence=max(0.0, min(1.0, 1.0 - std_dev / 2)),
    )


def _extract_json(raw: str) -> dict[str, object]:
    """Extract a JSON object from raw LLM text.

    Tries in order:
      1. Direct parse (native JSON mode — clean output)
      2. Strip markdown fences, then parse
      3. Regex search for first {...} block (handles preamble/postamble)
      4. Greedy {...} match (last resort for markdown-fenced multiline JSON)
    """
    # 1. Direct parse
    try:
        return cast("dict[str, object]", json.loads(raw))
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences (```json … ``` or ``` … ```)
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        return cast("dict[str, object]", json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    # 3. Non-greedy: first {...} block — works when JSON follows preamble text
    m = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
    if m:
        try:
            return cast("dict[str, object]", json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass

    # 4. Greedy: longest {...} span — handles multi-line JSON with nested values
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        return cast("dict[str, object]", json.loads(m.group(0)))

    raise ValueError(f"no parseable JSON object found in response: {raw!r}")


async def _call_one_judge(
    name: str,
    provider: BaseLLMProvider,
    model: str,
    system_prompt: str,
    user_message: str,
    *,
    max_retries: int = 2,
) -> tuple[float, str]:
    """Call one judge; return (score, reason).

    Retries up to *max_retries* times on parse failure (handles truncated /
    preamble-only responses from models that don't support JSON mode reliably).
    Falls back to (3.0, 'error…') only after all retries are exhausted.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    raw: str | None = None

    for attempt in range(1, max_retries + 2):  # attempts: 1, 2, 3
        try:
            log.debug(
                "judge_panel.judge_start  judge=%s  model=%s  attempt=%d",
                name, model, attempt,
            )
            response = await provider.complete_json(
                messages=[LLMMessage(role="user", content=user_message)],
                system=system_prompt,
                max_tokens=256,
                temperature=0.0,
                model=model,
            )
            raw = response.content.strip()
            log.debug(
                "judge_panel.raw_response  judge=%s  model=%s  attempt=%d  raw=%r",
                name, model, attempt, raw,
            )
            if not raw:
                raise ValueError("empty response from judge")

            parsed = _extract_json(raw)
            score = float(parsed["score"])  # type: ignore[arg-type]
            if not 1.0 <= score <= 5.0:
                raise ValueError(f"score out of range: {score}")
            reason = str(parsed.get("reason", ""))[:300]
            log.debug(
                "judge_panel.judge_ok  judge=%s  model=%s  score=%s",
                name, model, score,
            )
            return score, reason

        except Exception as exc:
            last_exc = exc
            if attempt <= max_retries:
                wait = 2.0 ** (attempt - 1)  # 1 s, 2 s
                log.warning(
                    "judge_panel.retry  judge=%s  model=%s  attempt=%d/%d"
                    "  error=%s  raw=%r  retry_in=%.1fs",
                    name, model, attempt, max_retries + 1, exc, raw, wait,
                )
                await asyncio.sleep(wait)
                raw = None  # reset for next attempt
            else:
                log.warning(
                    "judge_panel.judge_failed  judge=%s  model=%s"
                    "  attempts=%d  error=%s  raw=%r",
                    name, model, attempt, last_exc, raw,
                    exc_info=True,
                )
                return 3.0, f"error({type(last_exc).__name__}): {last_exc}"

    return 3.0, f"error({type(last_exc).__name__}): {last_exc}"  # unreachable


def _build_judges(
    native_models: dict[str, str],
    openrouter_models: dict[str, str],
) -> list[tuple[str, BaseLLMProvider, str]]:
    """Return list of (name, provider, model).

    When DEFAULT_LLM_PROVIDER=openrouter a single OpenRouter provider is used
    for all three judges with the pre-configured OpenRouter model slugs.
    Otherwise each judge calls its own native provider directly.
    """
    if settings.default_llm_provider == LLMProvider.OPENROUTER:
        try:
            provider = build_provider(LLMProvider.OPENROUTER, settings)
            return [
                (name, provider, model)
                for name, model in openrouter_models.items()
            ]
        except RuntimeError as exc:
            log.warning("judge_panel.openrouter_unavailable: %s", exc)
            return []

    # Native provider mode: skip any provider that has no API key
    provider_map = {
        "anthropic": LLMProvider.ANTHROPIC,
        "openai":    LLMProvider.OPENAI,
        "gemini":    LLMProvider.GEMINI,
    }
    judges = []
    for name, model in native_models.items():
        try:
            provider = build_provider(provider_map[name], settings)
            judges.append((name, provider, model))
        except RuntimeError:
            log.warning("judge_panel.provider_skipped: %s", name)
    return judges


async def run_jury(
    system_prompt: str,
    user_message: str,
    anthropic_model: str,
    openai_model: str,
    gemini_model: str,
    openrouter_anthropic: str,
    openrouter_openai: str,
    openrouter_gemini: str,
) -> JuryVerdict:
    """Run all three judges in parallel and aggregate their scores."""
    judges = _build_judges(
        native_models={
            "anthropic": anthropic_model,
            "openai":    openai_model,
            "gemini":    gemini_model,
        },
        openrouter_models={
            "anthropic": openrouter_anthropic,
            "openai":    openrouter_openai,
            "gemini":    openrouter_gemini,
        },
    )
    if not judges:
        raise RuntimeError("No judge providers are configured")

    tasks = [
        _call_one_judge(name, provider, model, system_prompt, user_message)
        for name, provider, model in judges
    ]
    results = await asyncio.gather(*tasks)

    raw_scores: dict[str, float] = {}
    raw_reasons: dict[str, str] = {}
    for (name, _, _), (score, reason) in zip(judges, results):
        raw_scores[name] = score
        raw_reasons[name] = reason

    return _aggregate(raw_scores, raw_reasons, settings.eval_dispute_threshold)
