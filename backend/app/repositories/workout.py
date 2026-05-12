from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import or_, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workout import WorkoutExercise, WorkoutSession, WorkoutSet


class WorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_history(
        self,
        user_id: uuid.UUID,
        date_from: date,
        date_to: date,
        limit: int = 500,
    ) -> list[WorkoutSession]:
        """Fetch sessions scoped to user_id — isolation enforced here."""
        result = await self._session.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.date >= date_from,
                WorkoutSession.date <= date_to,
                WorkoutSession.deleted_at.is_(None),
            )
            .options(
                selectinload(WorkoutSession.exercises)
                .selectinload(WorkoutExercise.sets)
            )
            .order_by(WorkoutSession.date.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> WorkoutSession | None:
        result = await self._session.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
                WorkoutSession.deleted_at.is_(None),
            )
            .options(
                selectinload(WorkoutSession.exercises)
                .selectinload(WorkoutExercise.sets)
            )
        )
        return result.scalar_one_or_none()

    async def get_sessions_paginated(
        self,
        user_id: uuid.UUID,
        cursor_date: date | None = None,
        cursor_id: uuid.UUID | None = None,
        page_size: int = 20,
    ) -> list[WorkoutSession]:
        q = (
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.deleted_at.is_(None),
            )
            .options(
                selectinload(WorkoutSession.exercises)
                .selectinload(WorkoutExercise.sets)
            )
            .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
            .limit(page_size + 1)
        )
        if cursor_date is not None and cursor_id is not None:
            q = q.where(
                or_(
                    WorkoutSession.date < cursor_date,
                    and_(WorkoutSession.date == cursor_date, WorkoutSession.id < cursor_id),
                )
            )
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def upsert_session(
        self,
        user_id: uuid.UUID,
        session_date: date,
        entries: list,  # list of (exercise_name, muscle_group, sets_data)
    ) -> WorkoutSession:
        """Find or create session for (user_id, date), append exercises."""
        result = await self._session.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.date == session_date,
                WorkoutSession.deleted_at.is_(None),
            )
            .options(selectinload(WorkoutSession.exercises))
        )
        session = result.scalar_one_or_none()
        if session is None:
            session = WorkoutSession(user_id=user_id, date=session_date)
            self._session.add(session)
            await self._session.flush()

        # Determine next order_index
        existing_count = len(session.exercises) if session.exercises else 0
        for i, (name, muscle_group, sets_data) in enumerate(entries):
            exercise = WorkoutExercise(
                session_id=session.id,
                name=name,
                muscle_group=muscle_group,
                order_index=existing_count + i,
            )
            self._session.add(exercise)
            await self._session.flush()
            for j, (reps, weight_kg) in enumerate(sets_data, start=1):
                ws = WorkoutSet(
                    exercise_id=exercise.id,
                    set_number=j,
                    reps=reps,
                    weight_kg=weight_kg,
                )
                self._session.add(ws)

        await self._session.flush()
        return session

    async def update_session_notes(
        self, session_id: uuid.UUID, user_id: uuid.UUID, notes: str | None
    ) -> WorkoutSession | None:
        session = await self.get_session(session_id, user_id)
        if session is None:
            return None
        session.notes = notes
        await self._session.flush()
        return session

    async def soft_delete(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        session = await self.get_session(session_id, user_id)
        if session is None:
            return False
        session.deleted_at = datetime.now(timezone.utc)
        await self._session.flush()
        return True
