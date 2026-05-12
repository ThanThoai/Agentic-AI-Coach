# Analytics Engine

**Component of:** Feature 2 — Workout History Analysis
**Last updated:** 2026-05-12

---

## Responsibility

Transform raw workout history (ORM rows from the DB) into a structured `AnalysisSummary`
that the LLM can read and reference. No LLM is involved here — these are deterministic
Python calculations.

The output of this layer is a **text block**, not a dict or JSON, that is injected
directly into the generation prompt.

---

## Module map

```
backend/app/workout/
├── normalizer.py    Unit conversion + input validation
├── catalog.py       Exercise → muscle group classification
└── analyzer.py      All metric computations + LLM context builder
```

---

## `normalizer.py` — Unit conversion

### Why normalise here, not in the DB model?

The DB always stores `weight_kg`. The API accepts `kg` or `lbs` from the client.
Normalisation happens **at the service layer**, before any row is written, and
before the analytics engine sees any data. The analytics engine never deals with units.

### Functions

```python
LBS_TO_KG = 0.453592

def normalize_weight(weight: float, unit: str) -> float:
    """Convert weight to kg. Raises ValueError for unknown units."""
    unit = unit.strip().lower()
    if unit in ("kg", "kilogram", "kilograms"):
        return round(weight, 2)
    if unit in ("lbs", "lb", "pound", "pounds"):
        return round(weight * LBS_TO_KG, 2)
    raise ValueError(f"Unknown weight unit: {unit!r}")


def normalize_set(s: SetInput) -> NormalizedSet:
    return NormalizedSet(
        set_number=s.set_number,
        reps=s.reps,
        weight_kg=normalize_weight(s.weight, s.unit),
        rpe=s.rpe,
        is_warmup=s.is_warmup,
    )


def normalize_session(entry: SessionCreateRequest) -> NormalizedSession:
    return NormalizedSession(
        date=entry.date,
        notes=entry.notes,
        exercises=[
            NormalizedExercise(
                name=entry.name.strip(),
                order_index=entry.order_index,
                sets=[normalize_set(s) for s in entry.sets],
            )
            for entry in entry.exercises
        ],
    )
```

### Validation rules

| Field | Rule | Error |
|-------|------|-------|
| `weight` | 0–1000 (kg equivalent) | `ValueError` |
| `reps` | 1–200 | `ValueError` |
| `unit` | `kg` \| `lbs` (case-insensitive) | `ValueError` |
| `set_number` | ≥ 1 | `ValueError` |
| `date` | not in the future (warn, not reject) | logged warning |

---

## `catalog.py` — Exercise → muscle group

### Design decisions

- Exercise names are **free text** — users type what they want.
- The catalog maps a cleaned name (lowercase, stripped) to one of 7 muscle groups.
- Unknown exercises get `muscle_group = "unknown"` — they contribute to volume totals
  but not to muscle-group analytics.
- Matching is **exact on cleaned name first**, then **substring match** as fallback.
- No LLM is used for classification — the catalog is a static dictionary that can be
  extended via PR.

### Muscle group taxonomy

```python
MuscleGroup = Literal[
    "chest", "back", "legs", "shoulders", "arms", "core", "unknown"
]

PUSH_GROUPS = {"chest", "shoulders", "arms"}
PULL_GROUPS = {"back"}
```

### Catalog structure

```python
# Excerpt — catalog.py

EXERCISE_CATALOG: dict[str, str] = {
    # Chest
    "bench press":               "chest",
    "incline bench press":       "chest",
    "decline bench press":       "chest",
    "dumbbell fly":              "chest",
    "cable fly":                 "chest",
    "push up":                   "chest",
    "chest dip":                 "chest",

    # Back
    "deadlift":                  "back",
    "barbell row":               "back",
    "dumbbell row":              "back",
    "pull up":                   "back",
    "chin up":                   "back",
    "lat pulldown":              "back",
    "seated cable row":          "back",
    "face pull":                 "back",

    # Legs
    "squat":                     "legs",
    "front squat":               "legs",
    "leg press":                 "legs",
    "romanian deadlift":         "legs",
    "rdl":                       "legs",
    "leg curl":                  "legs",
    "leg extension":             "legs",
    "walking lunge":             "legs",
    "hip thrust":                "legs",
    "calf raise":                "legs",

    # Shoulders
    "overhead press":            "shoulders",
    "ohp":                       "shoulders",
    "lateral raise":             "shoulders",
    "arnold press":              "shoulders",
    "rear delt fly":             "shoulders",

    # Arms
    "barbell curl":              "arms",
    "dumbbell curl":             "arms",
    "hammer curl":               "arms",
    "tricep pushdown":           "arms",
    "skull crusher":             "arms",
    "close grip bench press":    "arms",

    # Core
    "plank":                     "core",
    "ab wheel":                  "core",
    "crunch":                    "core",
    "hanging leg raise":         "core",
}
```

### Classification function

```python
def classify_exercise(name: str) -> str:
    """Return the muscle group for a given exercise name.

    Matching order:
    1. Exact match on cleaned name.
    2. Substring: cleaned name contains a catalog key (longest key wins).
    3. Fallback: "unknown".
    """
    cleaned = name.strip().lower()

    # 1. Exact match
    if cleaned in EXERCISE_CATALOG:
        return EXERCISE_CATALOG[cleaned]

    # 2. Substring — longest key that appears in the name
    matches = [
        (key, group)
        for key, group in EXERCISE_CATALOG.items()
        if key in cleaned
    ]
    if matches:
        best_key, group = max(matches, key=lambda x: len(x[0]))
        return group

    return "unknown"
```

### Examples

| User input | Cleaned | Match type | Result |
|-----------|---------|------------|--------|
| `"Bench Press"` | `"bench press"` | exact | `chest` |
| `"Paused Bench Press"` | `"paused bench press"` | substring (`"bench press"`) | `chest` |
| `"Close-grip bench press"` | `"close-grip bench press"` | substring (`"close grip bench press"`) | `arms` |
| `"RDL"` | `"rdl"` | exact | `legs` |
| `"Cable Crunch"` | `"cable crunch"` | substring (`"crunch"`) | `core` |
| `"Farmer's Walk"` | `"farmer's walk"` | no match | `unknown` |

---

## `analyzer.py` — Analytics engine

### Data structures

```python
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class SetStats:
    reps: int
    weight_kg: Decimal
    is_warmup: bool

    @property
    def volume(self) -> Decimal:
        return self.reps * self.weight_kg


@dataclass
class ExerciseStats:
    name: str
    muscle_group: str
    session_dates: list[date]         # sorted ascending
    total_volume_kg: Decimal          # sum of all sets × reps × kg
    avg_volume_per_session: Decimal
    max_weight_kg: Decimal            # heaviest single set (excluding warmup)
    last_session_volume: Decimal      # volume in the most recent session
    prev_session_volume: Decimal      # volume in the session before that
    weekly_trend_pct: float | None    # % change in weekly volume (None if < 2 weeks)
    session_count: int
    last_trained: date | None


@dataclass
class MuscleGroupStats:
    group: str
    total_volume_kg: Decimal
    sessions_per_week: float          # avg frequency
    last_trained: date | None
    exercises: list[str]              # distinct exercise names in this group


@dataclass
class AnalysisSummary:
    # Meta
    sessions_analysed: int
    date_range_from: date | None
    date_range_to: date | None
    insufficient_data: bool           # True when < 2 sessions

    # Exercise-level
    exercises: dict[str, ExerciseStats]       # keyed by exercise name
    muscle_groups: dict[str, MuscleGroupStats] # keyed by group name

    # Cross-cutting
    neglected_muscles: list[str]      # not trained in > NEGLECT_THRESHOLD_DAYS
    push_pull_ratio: float | None     # push_volume / pull_volume (None if either is 0)
    chest_back_ratio: float | None    # chest_volume / back_volume

    # Top-level totals
    total_volume_kg: Decimal
    most_trained_exercise: str | None
    strongest_exercise: str | None    # highest max_weight_kg

    # Raw sessions for context builder
    session_dates: list[date]
```

### Constants

```python
NEGLECT_THRESHOLD_DAYS = 14    # muscle group not trained in 14+ days = neglected
MIN_SESSIONS_FOR_TREND = 2     # need at least 2 data points for a trend
WARMUP_EXCLUDED_FROM_MAX = True
```

### Core functions

#### Session volume

```python
def compute_session_volume(
    sets: list[SetStats],
    exclude_warmup: bool = True,
) -> Decimal:
    """Total tonnage for one exercise in one session (sets × reps × kg)."""
    return sum(
        s.volume for s in sets
        if not (exclude_warmup and s.is_warmup)
    )
```

#### Exercise trends

```python
def compute_weekly_trend(
    session_dates: list[date],
    session_volumes: list[Decimal],
) -> float | None:
    """Week-over-week volume change as a percentage.

    Groups sessions into ISO weeks and compares the last two complete weeks.
    Returns None if fewer than 2 weeks of data exist.

    Example:
        Week 18: 2 400 kg → Week 19: 2 592 kg → +8.0 %
    """
    if len(session_dates) < MIN_SESSIONS_FOR_TREND:
        return None

    from collections import defaultdict
    weekly: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for d, v in zip(session_dates, session_volumes):
        key = (d.isocalendar().year, d.isocalendar().week)
        weekly[key] += v

    sorted_weeks = sorted(weekly.items())
    if len(sorted_weeks) < 2:
        return None

    prev_vol = sorted_weeks[-2][1]
    curr_vol = sorted_weeks[-1][1]
    if prev_vol == 0:
        return None
    return float((curr_vol - prev_vol) / prev_vol * 100)
```

#### Neglect detection

```python
def find_neglected_muscles(
    muscle_groups: dict[str, MuscleGroupStats],
    reference_date: date,
    threshold_days: int = NEGLECT_THRESHOLD_DAYS,
) -> list[str]:
    """Return muscle groups not trained within threshold_days of reference_date."""
    neglected = []
    for group, stats in muscle_groups.items():
        if group == "unknown":
            continue
        if stats.last_trained is None:
            neglected.append(group)
            continue
        days_since = (reference_date - stats.last_trained).days
        if days_since > threshold_days:
            neglected.append(group)
    return sorted(neglected)
```

#### Push/pull balance

```python
def compute_push_pull_ratio(
    muscle_groups: dict[str, MuscleGroupStats],
) -> float | None:
    """Push-to-pull volume ratio. 1.0 = balanced. > 1.0 = push-dominant."""
    push_vol = sum(
        s.total_volume_kg for g, s in muscle_groups.items() if g in PUSH_GROUPS
    )
    pull_vol = sum(
        s.total_volume_kg for g, s in muscle_groups.items() if g in PULL_GROUPS
    )
    if pull_vol == 0:
        return None
    return float(push_vol / pull_vol)
```

#### Main entry point

```python
def compute_analytics(
    sessions: list[WorkoutSession],
    reference_date: date | None = None,
) -> AnalysisSummary:
    """Full analytics pass over a list of ORM WorkoutSession objects.

    This is the single function the service layer calls. All sub-computations
    are called internally in dependency order.
    """
    if reference_date is None:
        from datetime import date as _date
        reference_date = _date.today()

    if not sessions:
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
            total_volume_kg=Decimal(0),
            most_trained_exercise=None,
            strongest_exercise=None,
            session_dates=[],
        )

    # ... (build ExerciseStats, MuscleGroupStats, then aggregate)
    insufficient_data = len(sessions) < MIN_SESSIONS_FOR_TREND

    # Return AnalysisSummary with all computed fields
    ...
```

---

## `build_llm_context()` — Structured text builder

This function converts `AnalysisSummary` into the text block that goes into the LLM prompt.
The output is **human-readable narrative + compact tables**, never raw JSON.

### Output example

```
=== WORKOUT ANALYSIS CONTEXT ===
Period: 12 Apr 2026 → 12 May 2026  |  Sessions: 14  |  Total volume: 68 400 kg

⚠ Data note: Only 14 sessions analysed. Trend confidence is moderate.

--- EXERCISE BREAKDOWN ---
Bench Press (chest)
  Sessions: 8  |  Avg volume/session: 2 100 kg  |  Max weight: 100 kg
  Trend (week-over-week): +8.0 %  ↑ Progressive
  Last trained: 2026-05-10

Squat (legs)
  Sessions: 6  |  Avg volume/session: 3 200 kg  |  Max weight: 130 kg
  Trend (week-over-week): -4.0 %  ↓ Slight decline
  Last trained: 2026-05-11

Romanian Deadlift (legs)
  Sessions: 5  |  Avg volume/session: 1 800 kg  |  Max weight: 90 kg
  Trend: insufficient data (< 2 weeks)
  Last trained: 2026-05-08

--- MUSCLE GROUP SUMMARY ---
chest:      8 sessions  |  total 16 800 kg  |  1.5 sessions/week
back:       5 sessions  |  total  9 000 kg  |  1.0 sessions/week  ⚠ below 2/week
legs:      10 sessions  |  total 38 400 kg  |  2.0 sessions/week
shoulders:  4 sessions  |  total  4 200 kg  |  0.5 sessions/week  ⚠ below 1/week
arms:       3 sessions  |  total  2 400 kg  |  0.5 sessions/week
core:       0 sessions  |  —  ⚠ NOT TRAINED in this period

--- BALANCE ---
Push / Pull ratio: 1.6  (push-dominant — consider adding back volume)
Chest / Back ratio: 1.87  (chest-dominant)

--- NEGLECTED MUSCLES (> 14 days) ---
core (last trained: never in this period)
```

### Builder signature

```python
def build_llm_context(
    summary: AnalysisSummary,
    question: str,
) -> str:
    """Convert AnalysisSummary to a structured text block for LLM injection.

    The question is passed in so the builder can emphasise the most relevant
    section (e.g., if the question is about Bench Press, put that exercise first).
    """
    ...
```

---

## Edge case handling

| Case | Detection | Handling |
|------|-----------|----------|
| Empty history | `sessions_analysed == 0` | Service returns early with "no workout history" message; LLM not called |
| Single session | `sessions_analysed < 2` | `insufficient_data = True`; context includes warning; LLM instructed to caveat |
| Unknown exercise | `muscle_group == "unknown"` | Included in volume totals; excluded from muscle-group analytics; noted in context |
| All same date | Only one distinct date | `weekly_trend_pct = None`; context flags "single-day data" |
| Zero-weight sets | `weight_kg == 0` | Valid (bodyweight exercises); included in volume as 0 kg; excluded from `max_weight_kg` |
| Warmup sets | `is_warmup = True` | Excluded from `max_weight_kg` and trend calculations; included in total volume with a note |
| Future dates | `date > today` | Logged warning at insert; analytics treats them as any other date |

---

## Testing

Analytics functions are **pure Python** — no DB, no LLM, no async. Test directly:

```python
# tests/mock/test_workout.py — analytics section

def test_volume_lbs_converted_to_kg():
    sets = [SetStats(reps=5, weight_kg=normalize_weight(225, "lbs"), is_warmup=False)]
    assert compute_session_volume(sets) == pytest.approx(510.1, rel=0.01)

def test_trend_positive():
    dates   = [date(2026, 4, 28), date(2026, 5,  5)]
    volumes = [Decimal("2000"),   Decimal("2200")]
    assert compute_weekly_trend(dates, volumes) == pytest.approx(10.0)

def test_trend_requires_two_sessions():
    assert compute_weekly_trend([date(2026, 5, 1)], [Decimal("2000")]) is None

def test_neglect_detected():
    stats = {"back": MuscleGroupStats(..., last_trained=date(2026, 4, 25))}
    result = find_neglected_muscles(stats, reference_date=date(2026, 5, 12))
    assert "back" in result

def test_empty_history_returns_summary():
    summary = compute_analytics([])
    assert summary.sessions_analysed == 0
    assert summary.insufficient_data is True

def test_unknown_exercise_excluded_from_muscle_groups():
    ...  # verify "Farmer's Walk" contributes to total_volume but not to muscle_groups["unknown"]
```
