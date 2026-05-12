"""Workout analysis pipeline runner for evaluation."""
from __future__ import annotations

import time
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.roster import find_athlete
from app.repositories.workout import WorkoutRepository
from app.schemas.workout import WorkoutAnalysisRequest, WorkoutAnalysisResponse
from app.services.workout import WorkoutPipelineProviders, WorkoutService

from ..schemas import TestCase


def _resolve_date(offset_days: int | None) -> date | None:
    if offset_days is None:
        return None
    return date.today() + timedelta(days=offset_days)


async def run_workout_case(
    case: TestCase,
    session: AsyncSession,
    providers: WorkoutPipelineProviders | None = None,
) -> tuple[WorkoutAnalysisResponse, int]:
    """Run workout analysis for one test case; return (response, latency_ms)."""
    if providers is None:
        providers = WorkoutPipelineProviders()

    athlete = find_athlete(case.athlete or "")
    if athlete is None:
        raise ValueError(f"Unknown athlete key: {case.athlete!r}")

    repo = WorkoutRepository(session)
    service = WorkoutService(repo, providers)

    date_from = _resolve_date(case.date_from_offset_days)
    date_to = _resolve_date(case.date_to_offset_days)

    request = WorkoutAnalysisRequest(
        question=case.question,
        date_from=date_from,
        date_to=date_to,
    )

    t0 = time.monotonic()
    response = await service.analyse(athlete.user_id, request)
    latency_ms = int((time.monotonic() - t0) * 1000)

    return response, latency_ms
