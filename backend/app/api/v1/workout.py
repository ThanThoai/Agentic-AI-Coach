from __future__ import annotations

import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.repositories.workout import WorkoutRepository
from app.schemas.workout import (
    ExerciseResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
    SetResponse,
    WorkoutAnalysisRequest,
    WorkoutAnalysisResponse,
    WorkoutEntryInput,
    WorkoutLogResponse,
)
from app.services.workout import WorkoutPipelineProviders, WorkoutService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/workout", tags=["workout"])


def get_workout_service(
    db: AsyncSession = Depends(get_db),
) -> WorkoutService:
    repo = WorkoutRepository(db)
    providers = WorkoutPipelineProviders()
    return WorkoutService(repo, providers)


@router.post(
    "/log",
    response_model=WorkoutLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log workout entries",
)
async def log_workout(
    entries: list[WorkoutEntryInput],
    user_id: uuid.UUID = Depends(get_current_user),
    service: WorkoutService = Depends(get_workout_service),
) -> WorkoutLogResponse:
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No entries provided",
        )
    if len(entries) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Too many entries (max 500)",
        )
    return await service.log_entries(user_id, entries)


@router.post(
    "/analyze",
    response_model=WorkoutAnalysisResponse,
    summary="Analyse workout history with AI",
)
async def analyze_workout(
    payload: WorkoutAnalysisRequest,
    user_id: uuid.UUID = Depends(get_current_user),
    service: WorkoutService = Depends(get_workout_service),
) -> WorkoutAnalysisResponse:
    return await service.analyse(user_id, payload)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List workout sessions (cursor paginated)",
)
async def list_sessions(
    user_id: uuid.UUID = Depends(get_current_user),
    cursor: str | None = Query(default=None, description="Opaque cursor from previous response"),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    repo = WorkoutRepository(db)
    cursor_date: date | None = None
    cursor_id: uuid.UUID | None = None
    if cursor:
        try:
            date_str, id_str = cursor.split(":")
            cursor_date = date.fromisoformat(date_str)
            cursor_id = uuid.UUID(id_str)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    sessions = await repo.get_sessions_paginated(user_id, cursor_date, cursor_id, page_size)
    has_more = len(sessions) > page_size
    page = sessions[:page_size]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = f"{last.date}:{last.id}"

    return SessionListResponse(
        data=[_session_to_response(s) for s in page],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Get a single workout session",
)
async def get_session(
    session_id: uuid.UUID = Path(...),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    repo = WorkoutRepository(db)
    session = await repo.get_session(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_response(session)


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Update session notes",
)
async def update_session(
    payload: SessionUpdateRequest,
    session_id: uuid.UUID = Path(...),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    repo = WorkoutRepository(db)
    async with db.begin():
        session = await repo.update_session_notes(session_id, user_id, payload.notes)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_response(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a workout session",
)
async def delete_session(
    session_id: uuid.UUID = Path(...),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = WorkoutRepository(db)
    async with db.begin():
        deleted = await repo.soft_delete(session_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


def _session_to_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        date=session.date,
        notes=session.notes,
        exercises=[
            ExerciseResponse(
                id=ex.id,
                name=ex.name,
                muscle_group=ex.muscle_group,
                order_index=ex.order_index,
                sets=[
                    SetResponse(
                        id=s.id,
                        set_number=s.set_number,
                        reps=s.reps,
                        weight_kg=s.weight_kg,
                        rpe=s.rpe,
                        is_warmup=s.is_warmup,
                    )
                    for s in ex.sets
                ],
            )
            for ex in session.exercises
        ],
    )
