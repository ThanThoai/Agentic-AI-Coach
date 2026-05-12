"""Workout ORM models — Feature 2: Workout History Analysis.

Imported by alembic/env.py to register tables on Base.metadata.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        Index(
            "idx_workout_sessions_user_date",
            "user_id",
            "date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    exercises: Mapped[list[WorkoutExercise]] = relationship(
        "WorkoutExercise",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        Index("idx_workout_exercises_session", "session_id"),
        Index("idx_workout_exercises_name", "name", "session_id"),
        Index(
            "idx_workout_exercises_muscle",
            "muscle_group",
            "session_id",
            postgresql_where=text("muscle_group IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    muscle_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    session: Mapped[WorkoutSession] = relationship(
        "WorkoutSession",
        back_populates="exercises",
    )
    sets: Mapped[list[WorkoutSet]] = relationship(
        "WorkoutSet",
        back_populates="exercise",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        Index("idx_workout_sets_exercise", "exercise_id"),
        CheckConstraint("reps BETWEEN 1 AND 200", name="ck_workout_sets_reps"),
        CheckConstraint("weight_kg >= 0", name="ck_workout_sets_weight_kg"),
        CheckConstraint("rpe BETWEEN 1 AND 10", name="ck_workout_sets_rpe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    is_warmup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    exercise: Mapped[WorkoutExercise] = relationship(
        "WorkoutExercise",
        back_populates="sets",
    )
