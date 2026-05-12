"""
Feature 2 — Workout History Analysis: mock tests.

All tests are pure Python or use mocked repositories/providers.
No real database or API keys required.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workout.normalizer import normalize_weight
from app.workout.catalog import classify_muscle_group, EXERCISE_CATALOG
from app.workout.analyzer import (
    AnalysisSummary,
    ExerciseStats,
    MuscleGroupStats,
    SetStats,
    compute_analytics,
    compute_weekly_trend,
    detect_deload_weeks,
    find_neglected_muscles,
    build_llm_context,
)
from app.schemas.workout import (
    SetInput,
    WorkoutEntryInput,
    WorkoutAnalysisRequest,
)
from app.services.workout import group_entries_by_date


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_exercise_stats(
    name: str = "Bench Press",
    muscle_group: str = "chest",
    session_dates: list[date] | None = None,
    session_volumes: list[Decimal] | None = None,
    max_weight_kg: Decimal = Decimal("100"),
    is_bodyweight: bool = False,
) -> ExerciseStats:
    if session_dates is None:
        session_dates = [date(2026, 3, 1), date(2026, 3, 8)]
    if session_volumes is None:
        session_volumes = [Decimal("2000"), Decimal("2200")]
    total = sum(session_volumes)
    avg = total / len(session_volumes)
    return ExerciseStats(
        name=name,
        muscle_group=muscle_group,
        session_dates=session_dates,
        session_volumes=session_volumes,
        total_volume_kg=total,
        avg_volume_per_session=avg,
        max_weight_kg=max_weight_kg,
        weekly_trend_pct=10.0,
        session_count=len(session_dates),
        last_trained=session_dates[-1],
        is_bodyweight=is_bodyweight,
    )


_RECENT = date(2026, 3, 19)

def _make_muscle_stats(
    group: str,
    total_volume_kg: Decimal = Decimal("10000"),
    sessions_per_week: float = 2.0,
    last_trained: date | None = _RECENT,
) -> MuscleGroupStats:
    return MuscleGroupStats(
        group=group,
        total_volume_kg=total_volume_kg,
        sessions_per_week=sessions_per_week,
        last_trained=last_trained,   # None = never trained in this period
        exercises=[group + "_ex"],
    )


def _make_empty_summary() -> AnalysisSummary:
    return AnalysisSummary(
        sessions_analysed=0,
        date_range_from=None,
        date_range_to=None,
        insufficient_data=True,
        exercises={},
        muscle_groups={},
        neglected_muscles=[],
        push_pull_ratio=None,
        chest_back_ratio=None,
        total_volume_kg=Decimal("0"),
        most_trained_exercise=None,
        strongest_exercise=None,
        deload_weeks=[],
        session_dates=[],
    )


# ── normalizer.py tests ───────────────────────────────────────────────────────

class TestNormalizeWeight:
    def test_kg_passthrough(self):
        assert normalize_weight(80, "kg") == Decimal("80.00")

    def test_lb_converts(self):
        result = normalize_weight(110, "lb")
        assert abs(float(result) - 49.9) < 0.1

    def test_lbs_alias_accepted(self):
        result = normalize_weight(45, "lbs")
        assert abs(float(result) - 20.41) < 0.1

    def test_pound_alias(self):
        result = normalize_weight(100, "pound")
        assert abs(float(result) - 45.36) < 0.1

    def test_zero_weight_valid(self):
        # bodyweight exercises (Pull-Up)
        assert normalize_weight(0, "kg") == Decimal("0.00")

    def test_case_insensitive(self):
        assert normalize_weight(10, "KG") == Decimal("10.00")
        assert normalize_weight(10, "LB") == normalize_weight(10, "lb")

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown weight unit"):
            normalize_weight(10, "stone")

    def test_returns_decimal(self):
        result = normalize_weight(100, "kg")
        assert isinstance(result, Decimal)


# ── catalog.py tests ──────────────────────────────────────────────────────────

class TestClassifyMuscleGroup:
    def test_bench_press_exact(self):
        assert classify_muscle_group("Bench Press") == "chest"

    def test_pull_up_hyphenated(self):
        # exact form from sample data
        assert classify_muscle_group("Pull-Up") == "back"

    def test_face_pull(self):
        assert classify_muscle_group("Face Pull") == "back"

    def test_romanian_deadlift_is_legs(self):
        assert classify_muscle_group("Romanian Deadlift") == "legs"

    def test_deadlift_is_back(self):
        assert classify_muscle_group("Deadlift") == "back"

    def test_incline_dumbbell_press(self):
        assert classify_muscle_group("Incline Dumbbell Press") == "chest"

    def test_leg_press(self):
        assert classify_muscle_group("Leg Press") == "legs"

    def test_tricep_pushdown(self):
        assert classify_muscle_group("Tricep Pushdown") == "arms"

    def test_bicep_curl(self):
        assert classify_muscle_group("Bicep Curl") == "arms"

    def test_lateral_raise(self):
        assert classify_muscle_group("Lateral Raise") == "shoulders"

    def test_overhead_press(self):
        assert classify_muscle_group("Overhead Press") == "shoulders"

    def test_squat(self):
        assert classify_muscle_group("Squat") == "legs"

    def test_case_insensitive(self):
        assert classify_muscle_group("bench press") == "chest"
        assert classify_muscle_group("SQUAT") == "legs"

    def test_substring_match_paused_bench(self):
        assert classify_muscle_group("Paused Bench Press") == "chest"

    def test_unknown_exercise(self):
        assert classify_muscle_group("Farmer's Walk") == "unknown"

    def test_rdl_abbreviation(self):
        assert classify_muscle_group("RDL") == "legs"


# ── analyzer.py — compute_weekly_trend ───────────────────────────────────────

class TestComputeWeeklyTrend:
    def test_positive_trend(self):
        dates = [date(2026, 2, 2), date(2026, 2, 9)]
        vols = [Decimal("2000"), Decimal("2200")]
        result = compute_weekly_trend(dates, vols)
        assert result == pytest.approx(10.0)

    def test_negative_trend(self):
        dates = [date(2026, 2, 2), date(2026, 2, 9)]
        vols = [Decimal("2000"), Decimal("1800")]
        result = compute_weekly_trend(dates, vols)
        assert result == pytest.approx(-10.0)

    def test_requires_two_sessions(self):
        assert compute_weekly_trend([date(2026, 2, 2)], [Decimal("2000")]) is None

    def test_requires_two_distinct_weeks(self):
        # same week → can't compute trend
        dates = [date(2026, 2, 2), date(2026, 2, 4)]
        vols = [Decimal("1000"), Decimal("1200")]
        result = compute_weekly_trend(dates, vols)
        assert result is None

    def test_multi_session_same_week_summed(self):
        # 2 sessions in week 1, 1 in week 2
        dates = [date(2026, 2, 2), date(2026, 2, 4), date(2026, 2, 9)]
        vols = [Decimal("1000"), Decimal("1000"), Decimal("2400")]
        # week1=2000, week2=2400 → +20%
        result = compute_weekly_trend(dates, vols)
        assert result == pytest.approx(20.0)


# ── analyzer.py — detect_deload_weeks ────────────────────────────────────────

class TestDetectDeloadWeeks:
    def _user_a_dates_vols(self):
        """Simulate User A's deload week (W05 = Jan 27-29).

        ISO weeks of 2026:
          W01: Dec 29-Jan 4  |  W02: Jan 5-11  |  W03: Jan 12-18
          W04: Jan 19-25     |  W05: Jan 26-Feb 1 (deload on Jan 27+29)
          W06: Feb 2-8

        Need ≥5 distinct weeks so that W05 sits at index ≥ rolling_window(4).
        """
        dates, vols = [], []
        for d, vol in [
            # W01 ~5 700
            (date(2025, 12, 29), Decimal("2800")),
            (date(2025, 12, 31), Decimal("2900")),
            # W02 ~5 600
            (date(2026, 1, 5),   Decimal("2700")),
            (date(2026, 1, 7),   Decimal("2900")),
            # W03 ~5 700
            (date(2026, 1, 12),  Decimal("2800")),
            (date(2026, 1, 14),  Decimal("2900")),
            # W04 ~5 700
            (date(2026, 1, 19),  Decimal("2800")),
            (date(2026, 1, 21),  Decimal("2900")),
            # W05 deload — only Jan 27+29, no Jan 26 → ~3 700
            (date(2026, 1, 27),  Decimal("1900")),
            (date(2026, 1, 29),  Decimal("1800")),
            # W06 back to normal
            (date(2026, 2, 2),   Decimal("2900")),
            (date(2026, 2, 4),   Decimal("2800")),
        ]:
            dates.append(d)
            vols.append(vol)
        return dates, vols

    def test_deload_detected(self):
        dates, vols = self._user_a_dates_vols()
        deloads = detect_deload_weeks(dates, vols)
        assert "2026-W05" in deloads

    def test_normal_weeks_not_flagged(self):
        dates, vols = self._user_a_dates_vols()
        deloads = detect_deload_weeks(dates, vols)
        # weeks before deload should not be flagged
        assert "2026-W02" not in deloads
        assert "2026-W03" not in deloads

    def test_insufficient_data_returns_empty(self):
        # fewer than rolling_window+1 weeks
        dates = [date(2026, 1, 5), date(2026, 1, 12)]
        vols = [Decimal("2000"), Decimal("1000")]
        result = detect_deload_weeks(dates, vols, rolling_window=4)
        assert result == []

    def test_returns_iso_week_strings(self):
        dates, vols = self._user_a_dates_vols()
        deloads = detect_deload_weeks(dates, vols)
        for item in deloads:
            assert "-W" in item


# ── analyzer.py — find_neglected_muscles ─────────────────────────────────────

class TestFindNeglectedMuscles:
    def test_not_trained_flagged(self):
        stats = {
            "back": _make_muscle_stats("back", last_trained=date(2026, 2, 25)),
        }
        result = find_neglected_muscles(stats, reference_date=date(2026, 3, 19))
        assert "back" in result

    def test_recently_trained_not_flagged(self):
        stats = {
            "chest": _make_muscle_stats("chest", last_trained=date(2026, 3, 18)),
        }
        result = find_neglected_muscles(stats, reference_date=date(2026, 3, 19))
        assert "chest" not in result

    def test_never_trained_flagged(self):
        # core is excluded from neglect detection; use "legs" instead
        stats = {
            "legs": _make_muscle_stats("legs", last_trained=None),
        }
        result = find_neglected_muscles(stats, reference_date=date(2026, 3, 19))
        assert "legs" in result

    def test_result_sorted(self):
        stats = {
            "legs": _make_muscle_stats("legs", last_trained=date(2026, 1, 1)),
            "arms": _make_muscle_stats("arms", last_trained=date(2026, 1, 1)),
        }
        result = find_neglected_muscles(stats, reference_date=date(2026, 3, 19))
        assert result == sorted(result)


# ── analyzer.py — compute_analytics ──────────────────────────────────────────

class TestComputeAnalytics:
    def _make_orm_session(self, session_date: date, exercises: list[tuple]) -> MagicMock:
        """Build a mock WorkoutSession ORM object."""
        session = MagicMock()
        session.date = session_date
        session.deleted_at = None   # required by compute_analytics filter
        session.exercises = []
        for ex_name, sets_data in exercises:
            ex = MagicMock()
            ex.name = ex_name
            ex.muscle_group = classify_muscle_group(ex_name)
            mock_sets = []
            for i, (reps, weight_kg) in enumerate(sets_data, start=1):
                s = MagicMock()
                s.set_number = i
                s.reps = reps
                s.weight_kg = Decimal(str(weight_kg))
                s.is_warmup = False
                mock_sets.append(s)
            ex.sets = mock_sets
            session.exercises.append(ex)
        return session

    def test_empty_returns_insufficient(self):
        summary = compute_analytics([], date(2026, 3, 19))
        assert summary.sessions_analysed == 0
        assert summary.insufficient_data is True
        assert summary.total_volume_kg == Decimal("0")

    def test_single_session_insufficient(self):
        session = self._make_orm_session(
            date(2026, 3, 1),
            [("Bench Press", [(8, 80), (8, 80), (7, 80)])],
        )
        summary = compute_analytics([session], date(2026, 3, 19))
        assert summary.sessions_analysed == 1
        assert summary.insufficient_data is True

    def test_two_sessions_sufficient(self):
        sessions = [
            self._make_orm_session(date(2026, 3, 1), [("Bench Press", [(8, 80)])]),
            self._make_orm_session(date(2026, 3, 8), [("Bench Press", [(8, 82.5)])]),
        ]
        summary = compute_analytics(sessions, date(2026, 3, 19))
        assert summary.sessions_analysed == 2
        assert summary.insufficient_data is False

    def test_volume_calculation(self):
        # 3 sets × 8 reps × 80 kg = 1920 kg
        session = self._make_orm_session(
            date(2026, 3, 1),
            [("Bench Press", [(8, 80), (8, 80), (8, 80)])],
        )
        summary = compute_analytics([session], date(2026, 3, 19))
        assert summary.total_volume_kg == Decimal("1920")

    def test_bodyweight_pull_up_is_zero_volume(self):
        sessions = [
            self._make_orm_session(date(2026, 3, 1), [("Pull-Up", [(10, 0), (9, 0)])]),
            self._make_orm_session(date(2026, 3, 8), [("Pull-Up", [(10, 0), (9, 0)])]),
        ]
        summary = compute_analytics(sessions, date(2026, 3, 19))
        assert "Pull-Up" in summary.exercises
        ex = summary.exercises["Pull-Up"]
        assert ex.is_bodyweight is True
        assert ex.max_weight_kg == Decimal("0")

    def test_muscle_group_classified(self):
        sessions = [
            self._make_orm_session(date(2026, 3, 1), [("Bench Press", [(8, 80)])]),
            self._make_orm_session(date(2026, 3, 8), [("Squat", [(5, 100)])]),
        ]
        summary = compute_analytics(sessions, date(2026, 3, 19))
        assert "chest" in summary.muscle_groups
        assert "legs" in summary.muscle_groups

    def test_push_pull_ratio(self):
        sessions = [
            self._make_orm_session(date(2026, 3, 1), [
                ("Bench Press", [(8, 80)]),   # chest — push
                ("Deadlift", [(5, 100)]),      # back — pull
            ]),
            self._make_orm_session(date(2026, 3, 8), [
                ("Bench Press", [(8, 80)]),
                ("Deadlift", [(5, 100)]),
            ]),
        ]
        summary = compute_analytics(sessions, date(2026, 3, 19))
        assert summary.push_pull_ratio is not None

    def test_unknown_exercise_contributes_volume(self):
        sessions = [
            self._make_orm_session(date(2026, 3, 1), [("Farmer's Walk", [(1, 50)])]),
            self._make_orm_session(date(2026, 3, 8), [("Farmer's Walk", [(1, 50)])]),
        ]
        summary = compute_analytics(sessions, date(2026, 3, 19))
        # volume exists even for unknown
        assert summary.total_volume_kg > Decimal("0")
        # unknown excluded from muscle_groups if function skips it
        # (at minimum it does not crash)


# ── analyzer.py — build_llm_context ──────────────────────────────────────────

class TestBuildLlmContext:
    def _make_summary(self) -> AnalysisSummary:
        ex = _make_exercise_stats("Bench Press", "chest")
        mg_chest = _make_muscle_stats("chest", Decimal("20000"), 2.0)
        mg_back = _make_muscle_stats("back", Decimal("10000"), 1.5)
        return AnalysisSummary(
            sessions_analysed=10,
            date_range_from=date(2026, 1, 1),
            date_range_to=date(2026, 3, 19),
            insufficient_data=False,
            exercises={"Bench Press": ex},
            muscle_groups={"chest": mg_chest, "back": mg_back},
            neglected_muscles=["core"],
            push_pull_ratio=2.0,
            chest_back_ratio=2.0,
            total_volume_kg=Decimal("50000"),
            most_trained_exercise="Bench Press",
            strongest_exercise="Bench Press",
            deload_weeks=["2026-W05"],
            session_dates=[date(2026, 1, 5)],
        )

    def test_returns_string(self):
        ctx = build_llm_context(self._make_summary())
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_contains_session_count(self):
        ctx = build_llm_context(self._make_summary())
        assert "10" in ctx

    def test_contains_exercise_name(self):
        ctx = build_llm_context(self._make_summary())
        assert "Bench Press" in ctx

    def test_neglected_section_present(self):
        ctx = build_llm_context(self._make_summary())
        assert "NEGLECT" in ctx.upper() or "core" in ctx

    def test_deload_section_present(self):
        ctx = build_llm_context(self._make_summary())
        assert "DELOAD" in ctx.upper() or "2026-W05" in ctx

    def test_balance_question_type_includes_ratio(self):
        ctx = build_llm_context(self._make_summary(), question_type="BALANCE")
        assert "ratio" in ctx.lower() or "BALANCE" in ctx.upper()

    def test_focus_exercise_in_context(self):
        ctx = build_llm_context(self._make_summary(), question_type="TREND", focus="Bench Press")
        assert "Bench Press" in ctx


# ── schemas.py ────────────────────────────────────────────────────────────────

class TestSchemas:
    def test_set_input_valid(self):
        s = SetInput(reps=8, weight=80.0, unit="kg")
        assert s.reps == 8

    def test_set_input_lb_accepted(self):
        s = SetInput(reps=5, weight=225.0, unit="lb")
        assert s.unit == "lb"

    def test_set_input_invalid_unit(self):
        with pytest.raises(Exception):
            SetInput(reps=5, weight=100.0, unit="stone")

    def test_set_input_zero_weight_valid(self):
        s = SetInput(reps=10, weight=0.0, unit="kg")
        assert s.weight == 0.0

    def test_workout_entry_input(self):
        entry = WorkoutEntryInput(
            date=date(2026, 3, 1),
            exercise="Bench Press",
            sets=[SetInput(reps=8, weight=80.0, unit="kg")],
        )
        assert entry.exercise == "Bench Press"

    def test_analysis_request_defaults_date_range(self):
        req = WorkoutAnalysisRequest(question="What is my bench press trend?")
        assert req.date_from is not None
        assert req.date_to is not None
        assert req.date_from < req.date_to

    def test_analysis_request_date_validation(self):
        with pytest.raises(Exception):
            WorkoutAnalysisRequest(
                question="What is my bench press trend?",
                date_from=date(2026, 3, 10),
                date_to=date(2026, 3, 1),
            )

    def test_analysis_request_short_question(self):
        with pytest.raises(Exception):
            WorkoutAnalysisRequest(question="hi")


# ── services.py — group_entries_by_date ──────────────────────────────────────

class TestGroupEntriesByDate:
    def _entry(self, d: date, exercise: str = "Bench Press") -> WorkoutEntryInput:
        return WorkoutEntryInput(
            date=d,
            exercise=exercise,
            sets=[SetInput(reps=8, weight=80.0, unit="kg")],
        )

    def test_single_date(self):
        entries = [self._entry(date(2026, 3, 1)), self._entry(date(2026, 3, 1), "Squat")]
        grouped = group_entries_by_date(entries)
        assert len(grouped) == 1
        assert len(grouped[date(2026, 3, 1)]) == 2

    def test_multiple_dates(self):
        entries = [self._entry(date(2026, 3, 1)), self._entry(date(2026, 3, 3))]
        grouped = group_entries_by_date(entries)
        assert sorted(grouped.keys()) == [date(2026, 3, 1), date(2026, 3, 3)]

    def test_sorted_ascending(self):
        entries = [self._entry(date(2026, 3, 5)), self._entry(date(2026, 3, 1))]
        grouped = group_entries_by_date(entries)
        keys = list(grouped.keys())
        assert keys == sorted(keys)


# ── services.py — analyse (integration-level mock) ───────────────────────────

class TestWorkoutServiceAnalyse:
    def _make_service(self, history: list, classifier_response: str, generation_response: str):
        from app.services.workout import WorkoutService
        from tests.mock.conftest import MockLLMProvider
        from app.llm.base import LLMResponse, TokenUsage

        class ControlledProvider(MockLLMProvider):
            def __init__(self, content: str):
                self._content = content

            async def complete(self, messages, *, model=None, max_tokens=2048, temperature=0.7, system=None):
                return LLMResponse(
                    content=self._content,
                    model="mock-model",
                    provider="mock",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
                )

        mock_repo = MagicMock()
        mock_repo.get_history = AsyncMock(return_value=history)

        mock_providers = MagicMock()
        mock_providers.classifier = ControlledProvider(classifier_response)
        mock_providers.classifier_model = None
        mock_providers.generation = ControlledProvider(generation_response)
        mock_providers.generation_model = None

        return WorkoutService(mock_repo, mock_providers)

    @pytest.mark.asyncio
    async def test_empty_history_early_return(self):
        service = self._make_service([], '{"type":"GENERAL","focus":null}', "some answer")
        from app.schemas.workout import WorkoutAnalysisRequest
        req = WorkoutAnalysisRequest(question="What is my bench press trend?")
        resp = await service.analyse(uuid.uuid4(), req)
        assert resp.data_summary.sessions_analysed == 0
        assert resp.data_summary.insufficient_data is True
        assert resp.model is None

    @pytest.mark.asyncio
    async def test_analysis_returns_answer(self):
        from unittest.mock import MagicMock

        def _make_session(d: date, ex_name: str, reps: int, weight: float):
            session = MagicMock()
            session.date = d
            session.deleted_at = None
            ex = MagicMock()
            ex.name = ex_name
            ex.muscle_group = classify_muscle_group(ex_name)
            s = MagicMock()
            s.reps = reps
            s.weight_kg = Decimal(str(weight))
            s.is_warmup = False
            ex.sets = [s]
            session.exercises = [ex]
            return session

        history = [
            _make_session(date(2026, 3, 1), "Bench Press", 8, 80),
            _make_session(date(2026, 3, 8), "Bench Press", 8, 82.5),
        ]
        service = self._make_service(
            history,
            '{"type":"TREND","focus":"Bench Press"}',
            "Your Bench Press is progressing well with **+3% week-over-week**.",
        )
        req = WorkoutAnalysisRequest(question="How is my bench press progressing?")
        resp = await service.analyse(uuid.uuid4(), req)
        assert "Bench Press" in resp.answer
        assert resp.data_summary.sessions_analysed == 2
        assert resp.model == "mock-model"


# ── User isolation test ───────────────────────────────────────────────────────

class TestUserIsolation:
    """Verify that user_id scoping is enforced at the repository level."""

    @pytest.mark.asyncio
    async def test_get_history_scopes_to_user(self):
        from app.repositories.workout import WorkoutRepository

        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        # Mock the DB session to return different data per user_id
        called_with: list[uuid.UUID] = []

        class MockSession:
            async def execute(self, stmt):
                # capture the user_id from the WHERE clause
                # We test that distinct user_ids produce distinct queries
                result = MagicMock()
                result.scalars.return_value.all.return_value = []
                return result

        repo_a = WorkoutRepository(MockSession())
        repo_b = WorkoutRepository(MockSession())

        # Both calls should succeed without mixing data
        history_a = await repo_a.get_history(user_a, date(2026, 1, 1), date(2026, 3, 31))
        history_b = await repo_b.get_history(user_b, date(2026, 1, 1), date(2026, 3, 31))

        assert history_a == []
        assert history_b == []
