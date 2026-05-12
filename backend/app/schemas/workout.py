from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.llm.base import TokenUsage


# ── Request schemas ────────────────────────────────────────────────────────────

class SetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reps: int = Field(..., ge=1, le=200)
    weight: float = Field(..., ge=0, le=1000)
    unit: str = Field(...)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        normalised = v.strip().lower()
        if normalised not in ("kg", "kilogram", "kilograms", "lb", "lbs", "pound", "pounds"):
            raise ValueError(f"Unknown unit {v!r}. Use 'kg' or 'lb'.")
        return normalised


class WorkoutEntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    exercise: str = Field(..., min_length=1, max_length=100)
    sets: list[SetInput] = Field(..., min_length=1, max_length=20)


class WorkoutAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=5, max_length=500)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "WorkoutAnalysisRequest":
        from datetime import date as _date, timedelta
        today = _date.today()
        if self.date_from is None:
            self.date_from = today - timedelta(days=90)
        if self.date_to is None:
            self.date_to = today
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self


class SessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=2000)


# ── Response schemas ───────────────────────────────────────────────────────────

class WorkoutLogResponse(BaseModel):
    sessions_created: int
    entries_logged: int
    dates: list[str]


class SetResponse(BaseModel):
    id: uuid.UUID
    set_number: int
    reps: int
    weight_kg: Decimal
    rpe: Decimal | None
    is_warmup: bool


class ExerciseResponse(BaseModel):
    id: uuid.UUID
    name: str
    muscle_group: str | None
    order_index: int
    sets: list[SetResponse]


class SessionResponse(BaseModel):
    id: uuid.UUID
    date: date
    notes: str | None
    exercises: list[ExerciseResponse]


class SessionListResponse(BaseModel):
    data: list[SessionResponse]
    next_cursor: str | None
    has_more: bool


class DataSummary(BaseModel):
    sessions_analysed: int
    date_range: dict[str, str]
    exercises_found: int
    muscle_groups_found: list[str]
    deload_weeks_detected: int
    insufficient_data: bool


class WorkoutAnalysisResponse(BaseModel):
    answer: str
    data_summary: DataSummary
    model: str | None
    usage: TokenUsage | None
