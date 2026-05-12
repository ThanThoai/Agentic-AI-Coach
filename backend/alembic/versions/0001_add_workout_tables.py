"""add workout tables

Revision ID: 0001
Revises: None
Create Date: 2026-05-12 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = "0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workout_sessions ──────────────────────────────────────────────────────
    op.create_table(
        "workout_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        "idx_workout_sessions_user_date",
        "workout_sessions",
        ["user_id", "date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── workout_exercises ─────────────────────────────────────────────────────
    op.create_table(
        "workout_exercises",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("muscle_group", sa.Text(), nullable=True),
        sa.Column(
            "order_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "idx_workout_exercises_session",
        "workout_exercises",
        ["session_id"],
    )
    op.create_index(
        "idx_workout_exercises_name",
        "workout_exercises",
        ["name", "session_id"],
    )
    op.create_index(
        "idx_workout_exercises_muscle",
        "workout_exercises",
        ["muscle_group", "session_id"],
        postgresql_where=sa.text("muscle_group IS NOT NULL"),
    )

    # ── workout_sets ──────────────────────────────────────────────────────────
    op.create_table(
        "workout_sets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column("rpe", sa.Numeric(3, 1), nullable=True),
        sa.Column(
            "is_warmup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint("reps BETWEEN 1 AND 200", name="ck_workout_sets_reps"),
        sa.CheckConstraint("weight_kg >= 0", name="ck_workout_sets_weight_kg"),
        sa.CheckConstraint("rpe BETWEEN 1 AND 10", name="ck_workout_sets_rpe"),
    )
    op.create_index(
        "idx_workout_sets_exercise",
        "workout_sets",
        ["exercise_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_workout_sets_exercise", table_name="workout_sets")
    op.drop_table("workout_sets")

    op.drop_index("idx_workout_exercises_muscle", table_name="workout_exercises")
    op.drop_index("idx_workout_exercises_name", table_name="workout_exercises")
    op.drop_index("idx_workout_exercises_session", table_name="workout_exercises")
    op.drop_table("workout_exercises")

    op.drop_index("idx_workout_sessions_user_date", table_name="workout_sessions")
    op.drop_table("workout_sessions")
