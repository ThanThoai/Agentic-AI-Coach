from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import structlog

from app.core.config import LLMProvider
from app.core.config import settings as _default_settings
from app.llm.base import BaseLLMProvider, LLMMessage
from app.llm.factory import get_step_provider
from app.prompts.workout import WORKOUT_ANALYSIS_SYSTEM, WORKOUT_CLASSIFIER_SYSTEM
from app.repositories.workout import WorkoutRepository
from app.schemas.workout import (
    DataSummary,
    WorkoutAnalysisRequest,
    WorkoutAnalysisResponse,
    WorkoutEntryInput,
    WorkoutLogResponse,
)
from app.workout.analyzer import build_llm_context, compute_analytics
from app.workout.catalog import classify_muscle_group
from app.workout.normalizer import normalize_weight

log = structlog.get_logger(__name__)

MAX_ANSWER_LENGTH = 2000


class WorkoutPipelineProviders:
    """LLM providers resolved for the workout analysis pipeline."""

    def __init__(self, cfg=_default_settings) -> None:
        self.classifier = get_step_provider(cfg.workout_classifier_provider, cfg)
        self.generation = get_step_provider(cfg.workout_generation_provider, cfg)

        self.classifier_model = self._resolve_model(
            cfg.workout_classifier_model,
            cfg.workout_classifier_provider,
            cfg.openrouter_workout_classifier_model,
            cfg,
        )
        self.generation_model = self._resolve_model(
            cfg.workout_generation_model,
            cfg.workout_generation_provider,
            cfg.openrouter_workout_generation_model,
            cfg,
        )

    @staticmethod
    def _resolve_model(
        explicit: str | None,
        step_provider: LLMProvider | None,
        openrouter_default: str,
        cfg,
    ) -> str | None:
        if explicit:
            return explicit
        effective = step_provider or cfg.default_llm_provider
        if effective == LLMProvider.OPENROUTER:
            return openrouter_default
        return None


def group_entries_by_date(
    entries: list[WorkoutEntryInput],
) -> dict[date, list[WorkoutEntryInput]]:
    groups: dict[date, list[WorkoutEntryInput]] = defaultdict(list)
    for entry in entries:
        groups[entry.date].append(entry)
    return dict(sorted(groups.items()))


async def classify_question(
    question: str,
    provider: BaseLLMProvider,
    model: str | None,
) -> tuple[str, str | None]:
    """Return (question_type, focus). Falls back to GENERAL on any error."""
    if len(question) < 15:
        return "GENERAL", None
    try:
        prompt = WORKOUT_CLASSIFIER_SYSTEM.format(question=question)
        resp = await provider.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=64,
            temperature=0.0,
            model=model,
        )
        content = resp.content.strip()
        if not content:
            return "GENERAL", None
        # Strip markdown code fences if the model wrapped the JSON
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        data = json.loads(content)
        q_type = str(data.get("type", "GENERAL")).upper()
        if q_type not in ("TREND", "BALANCE", "NEGLECT", "PLAN", "GENERAL"):
            q_type = "GENERAL"
        focus = data.get("focus") or None
        return q_type, focus
    except Exception as exc:
        log.warning(
            "workout.classifier.failed", err_type=type(exc).__name__, exc_info=True
        )
        return "GENERAL", None


class WorkoutService:
    def __init__(self, repo: WorkoutRepository, providers: WorkoutPipelineProviders) -> None:
        self._repo = repo
        self._providers = providers

    async def log_entries(
        self,
        user_id: uuid.UUID,
        entries: list[WorkoutEntryInput],
    ) -> WorkoutLogResponse:
        grouped = group_entries_by_date(entries)
        sessions_created = 0
        dates_affected = []

        async with self._repo._session.begin():
            for session_date, day_entries in grouped.items():
                exercise_rows = []
                for entry in day_entries:
                    muscle_group = classify_muscle_group(entry.exercise)
                    sets_data = [
                        (s.reps, normalize_weight(s.weight, s.unit))
                        for s in entry.sets
                    ]
                    exercise_rows.append((entry.exercise, muscle_group, sets_data))

                await self._repo.upsert_session(user_id, session_date, exercise_rows)
                sessions_created += 1
                dates_affected.append(str(session_date))

        return WorkoutLogResponse(
            sessions_created=sessions_created,
            entries_logged=len(entries),
            dates=dates_affected,
        )

    async def analyse(
        self,
        user_id: uuid.UUID,
        request: WorkoutAnalysisRequest,
    ) -> WorkoutAnalysisResponse:
        date_from = request.date_from
        date_to = request.date_to

        history = await self._repo.get_history(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        )

        if not history:
            return WorkoutAnalysisResponse(
                answer=(
                    "I don't have any workout data for the selected period. "
                    "Log some sessions first, then re-run the analysis."
                ),
                data_summary=DataSummary(
                    sessions_analysed=0,
                    date_range={"from": str(date_from), "to": str(date_to)},
                    exercises_found=0,
                    muscle_groups_found=[],
                    deload_weeks_detected=0,
                    insufficient_data=True,
                ),
                model=None,
                usage=None,
            )

        reference_date = date_to or date.today()
        summary = compute_analytics(history, reference_date)

        question_type = "GENERAL"
        focus = None
        if not summary.insufficient_data:
            question_type, focus = await classify_question(
                request.question,
                self._providers.classifier,
                self._providers.classifier_model,
            )

        context = build_llm_context(summary, question_type=question_type, focus=focus)

        llm_resp = await self._providers.generation.complete(
            messages=[
                LLMMessage(
                    role="user",
                    content=(
                        f"=== USER QUESTION ===\n{request.question}\n\n"
                        f"{context}\n\n"
                        "Answer the question using only the data shown above."
                    ),
                )
            ],
            system=WORKOUT_ANALYSIS_SYSTEM,
            max_tokens=600,
            temperature=0.3,
            model=self._providers.generation_model,
        )

        answer = llm_resp.content
        if len(answer) > MAX_ANSWER_LENGTH:
            answer = answer[:MAX_ANSWER_LENGTH] + "… [truncated]"

        return WorkoutAnalysisResponse(
            answer=answer,
            data_summary=DataSummary(
                sessions_analysed=summary.sessions_analysed,
                date_range={"from": str(date_from), "to": str(date_to)},
                exercises_found=len(summary.exercises),
                muscle_groups_found=[g for g in summary.muscle_groups if g != "unknown"],
                deload_weeks_detected=len(summary.deload_weeks),
                insufficient_data=summary.insufficient_data,
            ),
            model=llm_resp.model,
            usage=llm_resp.usage,
        )

    async def analyse_stream(
        self,
        user_id: uuid.UUID,
        request: WorkoutAnalysisRequest,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Same pipeline as analyse() but yields SSE-ready dicts for token streaming."""
        date_from = request.date_from
        date_to = request.date_to

        history = await self._repo.get_history(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        )

        if not history:
            yield {
                "type": "done",
                "answer": (
                    "I don't have any workout data for the selected period. "
                    "Log some sessions first, then re-run the analysis."
                ),
                "data_summary": DataSummary(
                    sessions_analysed=0,
                    date_range={"from": str(date_from), "to": str(date_to)},
                    exercises_found=0,
                    muscle_groups_found=[],
                    deload_weeks_detected=0,
                    insufficient_data=True,
                ).model_dump(),
                "model": None,
                "usage": None,
            }
            return

        reference_date = date_to or date.today()
        summary = compute_analytics(history, reference_date)

        question_type = "GENERAL"
        focus = None
        if not summary.insufficient_data:
            question_type, focus = await classify_question(
                request.question,
                self._providers.classifier,
                self._providers.classifier_model,
            )

        context = build_llm_context(summary, question_type=question_type, focus=focus)

        data_summary = DataSummary(
            sessions_analysed=summary.sessions_analysed,
            date_range={"from": str(date_from), "to": str(date_to)},
            exercises_found=len(summary.exercises),
            muscle_groups_found=[g for g in summary.muscle_groups if g != "unknown"],
            deload_weeks_detected=len(summary.deload_weeks),
            insufficient_data=summary.insufficient_data,
        )

        collected: list[str] = []
        async for token in self._providers.generation.stream(
            messages=[
                LLMMessage(
                    role="user",
                    content=(
                        f"=== USER QUESTION ===\n{request.question}\n\n"
                        f"{context}\n\n"
                        "Answer the question using only the data shown above."
                    ),
                )
            ],
            system=WORKOUT_ANALYSIS_SYSTEM,
            max_tokens=600,
            temperature=0.3,
            model=self._providers.generation_model,
        ):
            collected.append(token)
            yield {"type": "token", "content": token}

        answer = "".join(collected)

        yield {
            "type": "done",
            "answer": answer,
            "data_summary": data_summary.model_dump(),
            "model": self._providers.generation_model,
            "usage": None,
        }
