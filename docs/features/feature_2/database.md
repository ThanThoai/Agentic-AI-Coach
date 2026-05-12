# Database

**Component of:** Feature 2 — Workout History Analysis
**Last updated:** 2026-05-12

---

## Responsibility

Store workout history in a queryable relational structure that:
- Supports aggregate analytics (SUM, GROUP BY, time-window joins) efficiently
- Enforces user data isolation at the query layer (not the application layer)
- Preserves data on delete (soft deletes) for recovery
- Stores all weights in kg — unit conversion happens at the API boundary

---

## API input schema

The API accepts **flat per-exercise entries** (not pre-grouped sessions). Grouping by date
happens in the service layer. This matches how users log naturally — one exercise at a time.

```python
# backend/app/schemas/workout.py

class SetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reps:   int   = Field(..., ge=1, le=200)
    weight: float = Field(..., ge=0, le=1000)
    unit:   str   = Field(...)   # "kg" or "lb" (case-insensitive); "lb" not "lbs"

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        normalised = v.strip().lower()
        if normalised not in ("kg", "lb", "kilogram", "kilograms", "pound", "pounds"):
            raise ValueError(f"Unknown unit {v!r}. Use 'kg' or 'lb'.")
        return normalised


class WorkoutEntryInput(BaseModel):
    """One exercise in one calendar day. The service groups entries by date."""
    model_config = ConfigDict(extra="forbid")
    date:     date = Field(...)
    exercise: str  = Field(..., min_length=1, max_length=100)
    sets:     list[SetInput] = Field(..., min_length=1, max_length=20)


# POST /api/v1/workout/log accepts a list of these
WorkoutLogRequest = list[WorkoutEntryInput]   # 1–500 entries
```

### Service layer: grouping entries by date

Before any DB write, the service groups the flat list into sessions:

```python
def group_entries_by_date(
    entries: list[WorkoutEntryInput],
) -> dict[date, list[WorkoutEntryInput]]:
    """Group flat exercise entries into per-day buckets.

    Multiple entries for the same date become one session.
    Entries are ordered by their position in the input list (preserves user order).
    """
    from collections import defaultdict
    groups: dict[date, list[WorkoutEntryInput]] = defaultdict(list)
    for entry in entries:
        groups[entry.date].append(entry)
    return dict(sorted(groups.items()))  # ascending date order
```

The service then calls `normalize_weight` and `classify_exercise` on each entry
before building ORM objects and upserting via the repository.

---

## Schema

Three tables form a strict parent-child hierarchy:

```
workout_sessions (1 row per training day)
  └── workout_exercises (N rows per session — one per exercise)
        └── workout_sets (N rows per exercise — one per set)
```

### `workout_sessions`

```sql
CREATE TABLE workout_sessions (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date        DATE         NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ                          -- soft delete sentinel
);

-- Primary analytics pattern: user's history in date order
CREATE INDEX idx_workout_sessions_user_date
    ON workout_sessions (user_id, date DESC)
    WHERE deleted_at IS NULL;

-- Uniqueness: one session per user per calendar day
-- (multiple sessions per day allowed — enforced by application logic, not DB)
```

### `workout_exercises`

```sql
CREATE TABLE workout_exercises (
    id            UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID    NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,               -- free text: "Bench Press", "Paused Squat"
    muscle_group  TEXT,                           -- denormalized from catalog at insert
    order_index   INT     NOT NULL DEFAULT 0      -- display order within session
);

CREATE INDEX idx_workout_exercises_session
    ON workout_exercises (session_id);

-- Used by exercise-level trend queries
CREATE INDEX idx_workout_exercises_name
    ON workout_exercises (name, session_id);

-- Used by muscle-group analytics
CREATE INDEX idx_workout_exercises_muscle
    ON workout_exercises (muscle_group, session_id)
    WHERE muscle_group IS NOT NULL;
```

### `workout_sets`

```sql
CREATE TABLE workout_sets (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_id UUID            NOT NULL REFERENCES workout_exercises(id) ON DELETE CASCADE,
    set_number  INT             NOT NULL,          -- 1, 2, 3 ...
    reps        INT             NOT NULL CHECK (reps BETWEEN 1 AND 200),
    weight_kg   NUMERIC(6, 2)  NOT NULL CHECK (weight_kg >= 0),  -- always kg
    rpe         NUMERIC(3, 1)  CHECK (rpe BETWEEN 1 AND 10),     -- optional perceived effort
    is_warmup   BOOLEAN         NOT NULL DEFAULT false
);

CREATE INDEX idx_workout_sets_exercise
    ON workout_sets (exercise_id);
```

---

## SQLAlchemy ORM models

```python
# backend/app/models/workout.py

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, Index,
    Integer, Numeric, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        Index("idx_workout_sessions_user_date", "user_id", "date",
              postgresql_where="deleted_at IS NULL"),
    )

    id:         Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:    Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date:       Mapped[date]              = mapped_column(Date, nullable=False)
    notes:      Mapped[str | None]        = mapped_column(Text)
    created_at: Mapped[datetime]          = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime]          = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[datetime | None]   = mapped_column(nullable=True)

    exercises: Mapped[list[WorkoutExercise]] = relationship(
        "WorkoutExercise", back_populates="session",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.order_index",
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id:           Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id:   Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False)
    name:         Mapped[str]         = mapped_column(Text, nullable=False)
    muscle_group: Mapped[str | None]  = mapped_column(Text)        # populated by catalog at insert
    order_index:  Mapped[int]         = mapped_column(Integer, nullable=False, default=0)

    session: Mapped[WorkoutSession]     = relationship("WorkoutSession", back_populates="exercises")
    sets:    Mapped[list[WorkoutSet]]   = relationship(
        "WorkoutSet", back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="WorkoutSet.set_number",
    )


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("reps BETWEEN 1 AND 200", name="ck_sets_reps"),
        CheckConstraint("weight_kg >= 0",          name="ck_sets_weight"),
        CheckConstraint("rpe BETWEEN 1 AND 10",    name="ck_sets_rpe"),
    )

    id:          Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exercise_id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("workout_exercises.id", ondelete="CASCADE"), nullable=False)
    set_number:  Mapped[int]              = mapped_column(Integer, nullable=False)
    reps:        Mapped[int]              = mapped_column(Integer, nullable=False)
    weight_kg:   Mapped[Decimal]          = mapped_column(Numeric(6, 2), nullable=False)
    rpe:         Mapped[Decimal | None]   = mapped_column(Numeric(3, 1))
    is_warmup:   Mapped[bool]             = mapped_column(Boolean, nullable=False, default=False)

    exercise: Mapped[WorkoutExercise] = relationship("WorkoutExercise", back_populates="sets")
```

---

## Repository pattern

All DB access goes through `WorkoutRepository`. Routes and services never write queries directly.

```python
# backend/app/repositories/workout.py

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workout import WorkoutSession, WorkoutExercise, WorkoutSet


class WorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_history(
        self,
        user_id: uuid.UUID,
        date_from: date,
        date_to: date,
        limit: int = 500,
    ) -> list[WorkoutSession]:
        """Fetch sessions for a single user within a date range.

        user_id is always bound — this is the isolation guarantee.
        No amount of date_from/date_to manipulation can expose another user's data.
        """
        result = await self._session.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,   # isolation: always scoped
                WorkoutSession.date >= date_from,
                WorkoutSession.date <= date_to,
                WorkoutSession.deleted_at.is_(None),  # exclude soft-deleted
            )
            .options(
                selectinload(WorkoutSession.exercises)
                .selectinload(WorkoutExercise.sets)
            )
            .order_by(WorkoutSession.date.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,      # always passed — ownership check
    ) -> WorkoutSession | None:
        result = await self._session.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,   # isolation: reject other users' IDs
                WorkoutSession.deleted_at.is_(None),
            )
            .options(
                selectinload(WorkoutSession.exercises)
                .selectinload(WorkoutExercise.sets)
            )
        )
        return result.scalar_one_or_none()

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create_session(
        self,
        user_id: uuid.UUID,
        session_data: WorkoutSession,
    ) -> WorkoutSession:
        self._session.add(session_data)
        await self._session.flush()
        return session_data

    async def soft_delete(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a session. Returns False if not found or not owned."""
        from datetime import datetime, timezone
        session = await self.get_session(session_id, user_id)
        if session is None:
            return False
        session.deleted_at = datetime.now(timezone.utc)
        await self._session.flush()
        return True
```

---

## Alembic migration

```python
# backend/alembic/versions/xxxx_add_workout_tables.py

def upgrade() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id",         postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id",    postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date",       sa.Date,        nullable=False),
        sa.Column("notes",      sa.Text),
        sa.Column("created_at", sa.TIMESTAMPTZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMPTZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.TIMESTAMPTZ),
    )
    op.create_index(
        "idx_workout_sessions_user_date",
        "workout_sessions", ["user_id", "date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "workout_exercises",
        sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id",   postgresql.UUID(as_uuid=True), sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",         sa.Text,    nullable=False),
        sa.Column("muscle_group", sa.Text),
        sa.Column("order_index",  sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("idx_workout_exercises_session", "workout_exercises", ["session_id"])
    op.create_index("idx_workout_exercises_name",    "workout_exercises", ["name", "session_id"])

    op.create_table(
        "workout_sets",
        sa.Column("id",          postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workout_exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("set_number",  sa.Integer,       nullable=False),
        sa.Column("reps",        sa.Integer,       nullable=False),
        sa.Column("weight_kg",   sa.Numeric(6, 2), nullable=False),
        sa.Column("rpe",         sa.Numeric(3, 1)),
        sa.Column("is_warmup",   sa.Boolean,       nullable=False, server_default="false"),
        sa.CheckConstraint("reps BETWEEN 1 AND 200", name="ck_sets_reps"),
        sa.CheckConstraint("weight_kg >= 0",          name="ck_sets_weight"),
        sa.CheckConstraint("rpe BETWEEN 1 AND 10",    name="ck_sets_rpe"),
    )
    op.create_index("idx_workout_sets_exercise", "workout_sets", ["exercise_id"])


def downgrade() -> None:
    op.drop_table("workout_sets")
    op.drop_table("workout_exercises")
    op.drop_index("idx_workout_sessions_user_date", "workout_sessions")
    op.drop_table("workout_sessions")
```

---

## User data isolation — guarantee

Isolation is enforced at **two independent layers**, so a bug in one cannot compromise the other:

| Layer | Mechanism | What it prevents |
|-------|-----------|-----------------|
| **Repository** | `WHERE user_id = ?` bound parameter in every query | SQL injection or logic bug returning wrong user's rows |
| **Route handler** | `user_id = current_user.id` injected by `Depends(get_current_user)` | A caller supplying an arbitrary `user_id` in the request body |

The route handler **never accepts `user_id` as a client-supplied parameter**. It is always derived from the authenticated JWT:

```python
@router.post("/analyze")
async def analyze_workout(
    payload: WorkoutAnalysisRequest,   # contains only "question", "date_from", "date_to"
    current_user: User = Depends(get_current_user),
    repo: WorkoutRepository = Depends(get_workout_repository),
    ...
):
    # user_id comes ONLY from the auth token — never from the request body
    history = await repo.get_history(
        user_id=current_user.id,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
```

### Isolation test (required by spec)

```python
# tests/mock/test_workout.py

async def test_user_isolation(client_a, client_b, mock_db):
    """User B's analysis must not reference any data belonging to User A."""

    # User A logs a bench press session
    await client_a.post("/api/v1/workout/sessions", json={
        "date": "2026-05-01",
        "exercises": [{"name": "Bench Press", "order_index": 1,
                       "sets": [{"set_number": 1, "reps": 5, "weight": 100, "unit": "kg"}]}],
    })

    # User B asks about their workout history (they have none)
    response = await client_b.post("/api/v1/workout/analyze", json={
        "question": "What is my bench press progress?",
    })

    assert response.status_code == 200
    body = response.json()
    # The answer must not reference User A's data
    assert "100" not in body["answer"]
    assert "Bench Press" not in body["answer"] or "no workout" in body["answer"].lower()
    assert body["data_summary"]["sessions_analysed"] == 0
```
