"""Workout analytics engine — Feature 2: Workout History Analysis.

Pure Python: no async, no DB calls, no LLM.
Converts ORM WorkoutSession objects into structured AnalysisSummary dataclasses
and formats them into LLM-ready context strings.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.workout import WorkoutSession

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

NEGLECT_THRESHOLD_DAYS = 14
MIN_SESSIONS_FOR_TREND = 2
DELOAD_DROP_THRESHOLD = 0.20
DELOAD_ROLLING_WINDOW = 4


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SetStats:
    reps: int
    weight_kg: Decimal
    is_warmup: bool

    @property
    def volume(self) -> Decimal:
        return Decimal(str(self.reps)) * self.weight_kg


@dataclass
class ExerciseStats:
    name: str
    muscle_group: str
    session_dates: list[date]
    session_volumes: list[Decimal]
    total_volume_kg: Decimal
    avg_volume_per_session: Decimal
    max_weight_kg: Decimal
    weekly_trend_pct: float | None
    session_count: int
    last_trained: date | None
    is_bodyweight: bool


@dataclass
class MuscleGroupStats:
    group: str
    total_volume_kg: Decimal
    sessions_per_week: float
    last_trained: date | None
    exercises: list[str]


@dataclass
class AnalysisSummary:
    sessions_analysed: int
    date_range_from: date | None
    date_range_to: date | None
    insufficient_data: bool
    exercises: dict[str, ExerciseStats]
    muscle_groups: dict[str, MuscleGroupStats]
    neglected_muscles: list[str]
    push_pull_ratio: float | None
    chest_back_ratio: float | None
    total_volume_kg: Decimal
    most_trained_exercise: str | None
    strongest_exercise: str | None
    deload_weeks: list[str]
    session_dates: list[date]


# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────


def _iso_week(d: date) -> str:
    """Return ISO year-week string like '2026-W05'."""
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_weekly_trend(
    session_dates: list[date],
    session_volumes: list[Decimal],
) -> float | None:
    """Compare volume of last two complete ISO weeks.

    Returns percentage change as a float (e.g. 10.0 = +10%), or None if there
    are fewer than MIN_SESSIONS_FOR_TREND data points or fewer than two distinct
    weeks with data.
    """
    if len(session_dates) < MIN_SESSIONS_FOR_TREND:
        return None

    # Group total volume by ISO week
    week_volume: dict[str, Decimal] = defaultdict(Decimal)
    for d, vol in zip(session_dates, session_volumes):
        week_volume[_iso_week(d)] += vol

    sorted_weeks = sorted(week_volume.keys())
    if len(sorted_weeks) < 2:
        return None

    prev_week = sorted_weeks[-2]
    last_week = sorted_weeks[-1]

    prev_vol = week_volume[prev_week]
    last_vol = week_volume[last_week]

    if prev_vol == 0:
        return None  # can't compute meaningful % change from zero

    change = float((last_vol - prev_vol) / prev_vol * 100)
    return round(change, 2)


def find_neglected_muscles(
    muscle_groups: dict[str, MuscleGroupStats],
    reference_date: date,
    threshold_days: int = NEGLECT_THRESHOLD_DAYS,
) -> list[str]:
    """Return muscle groups not trained within threshold_days of reference_date."""
    neglected: list[str] = []
    cutoff = reference_date - timedelta(days=threshold_days)
    for group, stats in muscle_groups.items():
        if group in ("unknown", "full body", "cardio", "core"):
            continue
        if stats.last_trained is None or stats.last_trained < cutoff:
            neglected.append(group)
    return sorted(neglected)


def compute_push_pull_ratio(
    muscle_groups: dict[str, MuscleGroupStats],
) -> float | None:
    """Return push_volume / pull_volume, or None if either is zero."""
    from app.workout.catalog import PULL_GROUPS, PUSH_GROUPS

    push_vol = sum(
        float(stats.total_volume_kg)
        for group, stats in muscle_groups.items()
        if group in PUSH_GROUPS
    )
    pull_vol = sum(
        float(stats.total_volume_kg)
        for group, stats in muscle_groups.items()
        if group in PULL_GROUPS
    )

    if pull_vol == 0:
        return None
    return round(push_vol / pull_vol, 2)


def detect_deload_weeks(
    session_dates: list[date],
    session_volumes: list[Decimal],
    drop_threshold: float = DELOAD_DROP_THRESHOLD,
    rolling_window: int = DELOAD_ROLLING_WINDOW,
) -> list[str]:
    """Identify ISO weeks where volume dropped ≥ drop_threshold vs rolling avg.

    Algorithm:
    - Group volume by ISO week.
    - For each week (starting from index rolling_window), compute the rolling
      average of the preceding rolling_window weeks.
    - If that week's volume is < rolling_avg * (1 - drop_threshold), tag it.

    Returns list of ISO week strings like ["2026-W05"].
    """
    # Group total volume by ISO week preserving order
    week_order: list[str] = []
    week_volume: dict[str, Decimal] = defaultdict(Decimal)
    for d, vol in zip(session_dates, session_volumes):
        w = _iso_week(d)
        if w not in week_volume:
            week_order.append(w)
        week_volume[w] += vol

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_weeks: list[str] = []
    for w in week_order:
        if w not in seen:
            seen.add(w)
            unique_weeks.append(w)

    if len(unique_weeks) <= rolling_window:
        return []

    deload_weeks: list[str] = []
    for i in range(rolling_window, len(unique_weeks)):
        window_vols = [
            float(week_volume[unique_weeks[j]]) for j in range(i - rolling_window, i)
        ]
        rolling_avg = sum(window_vols) / rolling_window
        current_vol = float(week_volume[unique_weeks[i]])
        if rolling_avg > 0 and current_vol < rolling_avg * (1 - drop_threshold):
            deload_weeks.append(unique_weeks[i])

    return deload_weeks


# ──────────────────────────────────────────────────────────────────────────────
# Main analytics entry point
# ──────────────────────────────────────────────────────────────────────────────


def compute_analytics(
    sessions: list[WorkoutSession],
    reference_date: date,
) -> AnalysisSummary:
    """Convert a list of ORM WorkoutSession objects into AnalysisSummary.

    Only active (non-deleted) sessions are considered; caller should filter
    before passing, but this function skips any with deleted_at set as a
    safety measure.
    """
    active_sessions = [s for s in sessions if s.deleted_at is None]

    if not active_sessions:
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

    # ── Per-exercise accumulation ─────────────────────────────────────────────
    # exercise_name → list of (session_date, volume_for_that_session, max_weight)
    exercise_session_data: dict[str, list[tuple[date, Decimal, Decimal]]] = defaultdict(
        list
    )
    exercise_muscle_group: dict[str, str] = {}

    all_session_dates: list[date] = []

    for session in sorted(active_sessions, key=lambda s: s.date):
        all_session_dates.append(session.date)
        for exercise in session.exercises:
            muscle = exercise.muscle_group or "unknown"
            exercise_muscle_group[exercise.name] = muscle

            session_vol = Decimal("0")
            session_max_weight = Decimal("0")
            for ws in exercise.sets:
                vol = Decimal(str(ws.reps)) * ws.weight_kg
                session_vol += vol
                if ws.weight_kg > session_max_weight:
                    session_max_weight = ws.weight_kg

            exercise_session_data[exercise.name].append(
                (session.date, session_vol, session_max_weight)
            )

    # ── Build ExerciseStats ───────────────────────────────────────────────────
    exercise_stats: dict[str, ExerciseStats] = {}

    for ex_name, session_records in exercise_session_data.items():
        dates = [r[0] for r in session_records]
        vols = [r[1] for r in session_records]
        max_weights = [r[2] for r in session_records]

        total_vol = sum(vols, Decimal("0"))
        count = len(dates)
        avg_vol = total_vol / count if count > 0 else Decimal("0")
        max_weight = max(max_weights) if max_weights else Decimal("0")
        last_trained = max(dates) if dates else None
        trend = compute_weekly_trend(dates, vols)
        is_bodyweight = max_weight == Decimal("0")

        exercise_stats[ex_name] = ExerciseStats(
            name=ex_name,
            muscle_group=exercise_muscle_group[ex_name],
            session_dates=dates,
            session_volumes=vols,
            total_volume_kg=total_vol,
            avg_volume_per_session=avg_vol,
            max_weight_kg=max_weight,
            weekly_trend_pct=trend,
            session_count=count,
            last_trained=last_trained,
            is_bodyweight=is_bodyweight,
        )

    # ── Build MuscleGroupStats ────────────────────────────────────────────────
    # Group exercises by muscle group
    muscle_exercises: dict[str, list[str]] = defaultdict(list)
    muscle_volume: dict[str, Decimal] = defaultdict(Decimal)
    muscle_last_trained: dict[str, date] = {}
    muscle_session_dates: dict[str, set[date]] = defaultdict(set)

    for ex_name, stats in exercise_stats.items():
        group = stats.muscle_group
        muscle_exercises[group].append(ex_name)
        muscle_volume[group] += stats.total_volume_kg
        for d in stats.session_dates:
            muscle_session_dates[group].add(d)
        if stats.last_trained is not None:
            prev = muscle_last_trained.get(group)
            if prev is None or stats.last_trained > prev:
                muscle_last_trained[group] = stats.last_trained

    # Compute sessions_per_week for each muscle group
    date_range_from = min(all_session_dates) if all_session_dates else None
    date_range_to = max(all_session_dates) if all_session_dates else None

    total_weeks: float = 1.0
    if date_range_from and date_range_to:
        span_days = (date_range_to - date_range_from).days
        total_weeks = max(span_days / 7.0, 1.0)

    muscle_group_stats: dict[str, MuscleGroupStats] = {}
    for group in muscle_exercises:
        sessions_count = len(muscle_session_dates[group])
        spw = round(sessions_count / total_weeks, 2)
        muscle_group_stats[group] = MuscleGroupStats(
            group=group,
            total_volume_kg=muscle_volume[group],
            sessions_per_week=spw,
            last_trained=muscle_last_trained.get(group),
            exercises=sorted(muscle_exercises[group]),
        )

    # ── Derived metrics ───────────────────────────────────────────────────────
    neglected = find_neglected_muscles(muscle_group_stats, reference_date)
    push_pull = compute_push_pull_ratio(muscle_group_stats)

    # chest_back_ratio
    chest_vol = float(muscle_volume.get("chest", Decimal("0")))
    back_vol = float(muscle_volume.get("back", Decimal("0")))
    chest_back_ratio: float | None = None
    if back_vol > 0:
        chest_back_ratio = round(chest_vol / back_vol, 2)

    total_volume = sum(muscle_volume.values(), Decimal("0"))

    # most trained: highest session_count
    most_trained: str | None = None
    if exercise_stats:
        most_trained = max(
            exercise_stats,
            key=lambda k: exercise_stats[k].session_count,
        )

    # strongest: highest max_weight_kg (exclude bodyweight)
    non_bw = {k: v for k, v in exercise_stats.items() if not v.is_bodyweight}
    strongest: str | None = None
    if non_bw:
        strongest = max(non_bw, key=lambda k: non_bw[k].max_weight_kg)

    # Deload detection: aggregate all session volumes by date, then by week
    date_to_vol: dict[date, Decimal] = defaultdict(Decimal)
    for ex_name, stats in exercise_stats.items():
        for d, vol in zip(stats.session_dates, stats.session_volumes):
            date_to_vol[d] += vol

    sorted_dates = sorted(date_to_vol.keys())
    all_vols = [date_to_vol[d] for d in sorted_dates]
    deload_weeks = detect_deload_weeks(sorted_dates, all_vols)

    insufficient = len(active_sessions) < MIN_SESSIONS_FOR_TREND

    return AnalysisSummary(
        sessions_analysed=len(active_sessions),
        date_range_from=date_range_from,
        date_range_to=date_range_to,
        insufficient_data=insufficient,
        exercises=exercise_stats,
        muscle_groups=muscle_group_stats,
        neglected_muscles=neglected,
        push_pull_ratio=push_pull,
        chest_back_ratio=chest_back_ratio,
        total_volume_kg=total_volume,
        most_trained_exercise=most_trained,
        strongest_exercise=strongest,
        deload_weeks=deload_weeks,
        session_dates=sorted_dates,
    )


# ──────────────────────────────────────────────────────────────────────────────
# LLM context builder
# ──────────────────────────────────────────────────────────────────────────────


def build_llm_context(
    summary: AnalysisSummary,
    question_type: str = "GENERAL",
    focus: str | None = None,
) -> str:
    """Produce a structured text block suitable for an LLM system/user prompt.

    question_type controls section ordering:
    - "BALANCE"  → BALANCE section appears first after the header
    - "NEGLECT"  → NEGLECTED MUSCLES section appears first after the header
    - "GENERAL"  → default order

    focus (exercise name) → that exercise appears first in EXERCISE BREAKDOWN.
    """
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    date_from = (
        summary.date_range_from.isoformat() if summary.date_range_from else "N/A"
    )
    date_to = summary.date_range_to.isoformat() if summary.date_range_to else "N/A"
    lines.append("=== WORKOUT HISTORY ANALYSIS ===")
    lines.append(f"Period: {date_from} → {date_to}")
    lines.append(f"Sessions analysed: {summary.sessions_analysed}")
    lines.append(f"Total volume: {summary.total_volume_kg:.1f} kg")
    lines.append("")

    if summary.insufficient_data:
        lines.append(
            "⚠ WARNING: Insufficient data for reliable trend analysis "
            f"(need ≥{MIN_SESSIONS_FOR_TREND} sessions, "
            f"have {summary.sessions_analysed})."
        )
        lines.append("")

    # ── Section builders ──────────────────────────────────────────────────────

    def _exercise_breakdown() -> list[str]:
        section: list[str] = ["--- EXERCISE BREAKDOWN ---"]
        if not summary.exercises:
            section.append("No exercise data available.")
            section.append("")
            return section

        # Order: focus exercise first, then by total volume descending
        ordered = sorted(
            summary.exercises.values(),
            key=lambda e: (
                0 if (focus and e.name.lower() == focus.lower()) else 1,
                -float(e.total_volume_kg),
            ),
        )

        for ex in ordered:
            trend_str = (
                f"{ex.weekly_trend_pct:+.1f}%/week"
                if ex.weekly_trend_pct is not None
                else "trend: N/A"
            )
            weight_str = (
                "bodyweight" if ex.is_bodyweight else f"{ex.max_weight_kg:.1f} kg max"
            )
            last_str = ex.last_trained.isoformat() if ex.last_trained else "never"
            section.append(
                f"  {ex.name} [{ex.muscle_group}]"
                f" | sessions: {ex.session_count}"
                f" | total vol: {ex.total_volume_kg:.1f} kg"
                f" | avg/session: {ex.avg_volume_per_session:.1f} kg"
                f" | {weight_str}"
                f" | {trend_str}"
                f" | last: {last_str}"
            )
        section.append("")
        return section

    def _muscle_group_summary() -> list[str]:
        section: list[str] = ["--- MUSCLE GROUP SUMMARY ---"]
        if not summary.muscle_groups:
            section.append("No muscle group data available.")
            section.append("")
            return section

        ordered = sorted(
            summary.muscle_groups.values(),
            key=lambda m: -float(m.total_volume_kg),
        )
        for mg in ordered:
            last_str = mg.last_trained.isoformat() if mg.last_trained else "never"
            section.append(
                f"  {mg.group}"
                f" | total vol: {mg.total_volume_kg:.1f} kg"
                f" | {mg.sessions_per_week:.1f} sessions/week"
                f" | last trained: {last_str}"
                f" | exercises: {', '.join(mg.exercises)}"
            )
        section.append("")
        return section

    def _balance_section() -> list[str]:
        section: list[str] = ["--- BALANCE ---"]
        if summary.push_pull_ratio is not None:
            ratio = summary.push_pull_ratio
            if ratio > 1.5:
                assessment = "push-dominant (consider more pull work)"
            elif ratio < 0.67:
                assessment = "pull-dominant (consider more push work)"
            else:
                assessment = "balanced"
            section.append(f"  Push/Pull ratio: {ratio:.2f} ({assessment})")
        else:
            section.append("  Push/Pull ratio: N/A (insufficient data)")

        if summary.chest_back_ratio is not None:
            ratio = summary.chest_back_ratio
            if ratio > 1.3:
                assessment = "chest-dominant"
            elif ratio < 0.77:
                assessment = "back-dominant"
            else:
                assessment = "balanced"
            section.append(f"  Chest/Back ratio: {ratio:.2f} ({assessment})")
        else:
            section.append("  Chest/Back ratio: N/A (insufficient data)")
        section.append("")
        return section

    def _neglected_section() -> list[str]:
        if not summary.neglected_muscles:
            return []
        section: list[str] = ["--- NEGLECTED MUSCLES ---"]
        section.append(
            f"  Muscle groups not trained in the last {NEGLECT_THRESHOLD_DAYS} days:"
        )
        for mg in summary.neglected_muscles:
            mg_stats = summary.muscle_groups.get(mg)
            last_str = (
                mg_stats.last_trained.isoformat()
                if mg_stats and mg_stats.last_trained
                else "never"
            )
            section.append(f"    • {mg} (last trained: {last_str})")
        section.append("")
        return section

    def _deload_section() -> list[str]:
        if not summary.deload_weeks:
            return []
        section: list[str] = ["--- DELOAD WEEKS DETECTED ---"]
        section.append(
            f"  Weeks with ≥{int(DELOAD_DROP_THRESHOLD * 100)}% volume drop vs "
            f"{DELOAD_ROLLING_WINDOW}-week rolling avg:"
        )
        for week in summary.deload_weeks:
            section.append(f"    • {week}")
        section.append("")
        return section

    # ── Assemble sections in order ────────────────────────────────────────────
    qt = question_type.upper()

    if qt == "BALANCE":
        lines += _balance_section()
        lines += _exercise_breakdown()
        lines += _muscle_group_summary()
        lines += _neglected_section()
        lines += _deload_section()
    elif qt == "NEGLECT":
        lines += _neglected_section()
        lines += _muscle_group_summary()
        lines += _exercise_breakdown()
        lines += _balance_section()
        lines += _deload_section()
    else:
        # GENERAL — default order
        lines += _exercise_breakdown()
        lines += _muscle_group_summary()
        lines += _balance_section()
        lines += _neglected_section()
        lines += _deload_section()

    lines.append("=== END OF ANALYSIS ===")
    return "\n".join(lines)
