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

The DB always stores `weight_kg`. The API accepts `"kg"` or `"lb"` from the client.
Normalisation happens **at the service layer**, before any row is written, and
before the analytics engine sees any data. The analytics engine never deals with units.

> **Unit note**: sample data uses `"lb"` (not `"lbs"`). Both aliases are accepted;
> pydantic validation normalises to lowercase before reaching this function.

### Functions

```python
LBS_TO_KG = 0.453592

def normalize_weight(weight: float, unit: str) -> float:
    """Convert weight to kg. Raises ValueError for unknown units.

    Accepted: "kg", "kilogram", "kilograms", "lb", "lbs", "pound", "pounds"
    Zero weight is valid — bodyweight exercises (Pull-Up, etc.) use weight=0, unit="kg".
    """
    unit = unit.strip().lower()
    if unit in ("kg", "kilogram", "kilograms"):
        return round(weight, 2)
    if unit in ("lb", "lbs", "pound", "pounds"):
        return round(weight * LBS_TO_KG, 2)
    raise ValueError(f"Unknown weight unit: {unit!r}")


def normalize_entry(entry: WorkoutEntryInput) -> NormalizedEntry:
    """Normalize a single flat exercise entry from the API input."""
    return NormalizedEntry(
        date=entry.date,
        exercise=entry.exercise.strip(),
        sets=[
            NormalizedSet(
                reps=s.reps,
                weight_kg=normalize_weight(s.weight, s.unit),
                is_warmup=False,   # input schema does not expose is_warmup yet
            )
            for s in entry.sets
        ],
    )
```

### Validation rules

| Field | Rule | Error |
|-------|------|-------|
| `weight` | 0–1000 (0 = bodyweight, e.g. Pull-Up) | `ValueError` |
| `reps` | 1–200 | `ValueError` |
| `unit` | `"kg"` or `"lb"` (case-insensitive; `"lb"` not `"lbs"`) | `ValueError` |
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
    # Chest — includes exercises found in sample data
    "bench press":               "chest",
    "incline bench press":       "chest",
    "incline dumbbell press":    "chest",   # User A sample data
    "decline bench press":       "chest",
    "dumbbell fly":              "chest",
    "cable fly":                 "chest",
    "push up":                   "chest",
    "chest dip":                 "chest",

    # Back — "pull-up" (hyphenated) is the exact form in sample data;
    #         cleaned to "pull-up" after strip().lower(), so we need both forms
    "deadlift":                  "back",    # User A (distinct from Romanian Deadlift)
    "barbell row":               "back",
    "dumbbell row":              "back",
    "pull-up":                   "back",    # exact form in sample data (hyphenated)
    "pull up":                   "back",    # hyphen-free alias
    "chin up":                   "back",
    "chin-up":                   "back",
    "lat pulldown":              "back",
    "seated cable row":          "back",
    "face pull":                 "back",    # User A/B sample data

    # Legs
    "squat":                     "legs",
    "front squat":               "legs",
    "leg press":                 "legs",    # User A sample data
    "romanian deadlift":         "legs",    # User A sample data
    "rdl":                       "legs",
    "leg curl":                  "legs",
    "leg extension":             "legs",
    "walking lunge":             "legs",
    "hip thrust":                "legs",
    "calf raise":                "legs",

    # Shoulders
    "overhead press":            "shoulders",
    "ohp":                       "shoulders",
    "lateral raise":             "shoulders",   # User B sample data
    "arnold press":              "shoulders",
    "rear delt fly":             "shoulders",

    # Arms
    "barbell curl":              "arms",
    "bicep curl":                "arms",        # User A/B sample data
    "dumbbell curl":             "arms",
    "hammer curl":               "arms",
    "tricep pushdown":           "arms",        # User A/B sample data
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
| `"Pull-Up"` | `"pull-up"` | exact | `back` |
| `"Face Pull"` | `"face pull"` | exact | `back` |
| `"Romanian Deadlift"` | `"romanian deadlift"` | exact | `legs` |
| `"Incline Dumbbell Press"` | `"incline dumbbell press"` | exact | `chest` |
| `"Tricep Pushdown"` | `"tricep pushdown"` | exact | `arms` |
| `"Bicep Curl"` | `"bicep curl"` | exact | `arms` |
| `"Lateral Raise"` | `"lateral raise"` | exact | `shoulders` |
| `"Paused Bench Press"` | `"paused bench press"` | substring (`"bench press"`) | `chest` |
| `"RDL"` | `"rdl"` | exact | `legs` |
| `"Cable Crunch"` | `"cable crunch"` | substring (`"crunch"`) | `core` |
| `"Farmer's Walk"` | `"farmer's walk"` | no match | `unknown` |

> **Deadlift vs Romanian Deadlift**: `"deadlift"` maps to `back` (hip hinge,
> primarily a back exercise); `"romanian deadlift"` maps to `legs` (hamstring-dominant).
> The substring match for `"deadlift"` would also trigger on `"romanian deadlift"` — but
> exact match wins first, so the correct group is returned without ambiguity.

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

    # Deload detection
    deload_weeks: list[str]           # ISO week strings where volume dropped > threshold
                                      # e.g. ["2026-W05"] for User A's Jan 27-29 week

    # Raw sessions for context builder
    session_dates: list[date]
```

### Constants

```python
NEGLECT_THRESHOLD_DAYS = 14    # muscle group not trained in 14+ days = neglected
MIN_SESSIONS_FOR_TREND = 2     # need at least 2 data points for a trend
DELOAD_DROP_THRESHOLD = 0.20   # > 20% weekly volume drop vs 4-week rolling average
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

#### Deload detection

```python
def detect_deload_weeks(
    session_dates: list[date],
    session_volumes: list[Decimal],
    drop_threshold: float = DELOAD_DROP_THRESHOLD,
    rolling_window: int = 4,
) -> list[str]:
    """Identify ISO weeks where total volume dropped > threshold vs. rolling average.

    Uses a 4-week rolling average as the baseline. A week with volume more than
    drop_threshold (default 20%) below that average is flagged as a deload week.

    Returns a list of ISO week strings: e.g. ["2026-W05"].

    Example (User A's data):
        Week 4 (Jan 20-26): ~8 400 kg  ─┐
        Week 5 (Jan 27-Feb 2): ~6 000 kg ← flagged (-28% vs avg) — confirmed deload
        Week 6 (Feb 3-9): ~8 800 kg
    """
    from collections import defaultdict
    weekly: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for d, v in zip(session_dates, session_volumes):
        key = (d.isocalendar().year, d.isocalendar().week)
        weekly[key] += v

    sorted_weeks = sorted(weekly.items())
    if len(sorted_weeks) < rolling_window + 1:
        return []

    deload_weeks = []
    for i in range(rolling_window, len(sorted_weeks)):
        (year, week), curr_vol = sorted_weeks[i]
        avg = sum(v for _, v in sorted_weeks[i - rolling_window:i]) / rolling_window
        if avg > 0 and curr_vol < avg * (1 - drop_threshold):
            deload_weeks.append(f"{year}-W{week:02d}")

    return deload_weeks
```

> **Why 4-week rolling average?** A single-week comparison (`prev_vol → curr_vol`) is
> noisy — one missed session flips the signal. A 4-week average smooths weekly variation
> and aligns with standard periodisation cycles. User A's Jan 27-29 deload drops ~25%
> vs. the preceding 4-week average, which is comfortably above the 20% threshold.

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

The example below is derived from **User A (Alex)** Jan 2 – Mar 19 2026 sample data
(PPL split, 3 months, ~24 sessions):

```
=== WORKOUT ANALYSIS CONTEXT ===
Period: 02 Jan 2026 → 19 Mar 2026  |  Sessions: 24  |  Total volume: 142 800 kg

--- EXERCISE BREAKDOWN ---
Bench Press (chest)
  Sessions: 12  |  Avg volume/session: 2 520 kg  |  Max weight: 100 kg
  Trend (week-over-week): +8.5 %  ↑ Progressive
  Last trained: 2026-03-19

Squat (legs)
  Sessions: 8  |  Avg volume/session: 4 050 kg  |  Max weight: 120 kg
  Trend (week-over-week): +6.7 %  ↑ Progressive
  Last trained: 2026-03-17

Overhead Press (shoulders)
  Sessions: 8  |  Avg volume/session: 935 kg  |  Max weight: 55 kg
  Trend (week-over-week): +5.3 %  ↑ Progressive
  Last trained: 2026-03-19

Pull-Up (back)
  Sessions: 8  |  Avg volume/session: 0 kg  |  [bodyweight — reps only]
  Max weight: 0 kg (bodyweight)
  Trend: measured by reps — 9.5 avg reps/session
  Last trained: 2026-03-18

Romanian Deadlift (legs)
  Sessions: 8  |  Avg volume/session: 1 980 kg  |  Max weight: 90 kg
  Trend (week-over-week): +4.2 %  ↑ Progressive
  Last trained: 2026-03-17

Tricep Pushdown (arms)
  Sessions: 8  |  Avg volume/session: 610 kg  |  Max weight: 30 kg
  Trend (week-over-week): stable
  Last trained: 2026-03-19

Bicep Curl (arms)
  Sessions: 8  |  Avg volume/session: 540 kg  |  Max weight: 17.5 kg
  Trend (week-over-week): stable
  Last trained: 2026-03-18

--- MUSCLE GROUP SUMMARY ---
chest:      12 sessions  |  total 30 240 kg  |  1.9 sessions/week
back:       16 sessions  |  total 14 400 kg  |  2.5 sessions/week
legs:       16 sessions  |  total 48 240 kg  |  2.5 sessions/week
shoulders:   8 sessions  |  total  7 480 kg  |  1.3 sessions/week
arms:       16 sessions  |  total  9 200 kg  |  2.5 sessions/week
core:        0 sessions  |  —  ⚠ NOT TRAINED in this period

--- BALANCE ---
Push / Pull ratio: 1.2  (slightly push-dominant)
Chest / Back ratio: 2.1  (chest-dominant by volume — note: back includes bodyweight Pull-Up)

--- NEGLECTED MUSCLES (> 14 days) ---
core (last trained: never in this period)

--- DELOAD WEEKS ---
2026-W05 (Jan 27–29): total volume ~5 900 kg  (-26 % vs 4-week avg of ~8 000 kg)
  → Bench Press: 60 kg (-20 % vs normal 75 kg)
  → Overhead Press: 30 kg (-29 % vs normal 42.5 kg)
  → Squat: 80 kg (-24 % vs normal 105 kg)
```

### Builder signature

```python
def build_llm_context(
    summary: AnalysisSummary,
    question_type: str = "GENERAL",
    focus: str | None = None,
) -> str:
    """Convert AnalysisSummary to a structured text block for LLM injection.

    question_type and focus come from the Haiku question classifier (llm-analysis.md).
    When focus is set (e.g. "Bench Press"), that exercise section is placed first.
    When question_type is "NEGLECT", the neglected muscles section is placed first.
    When question_type is "BALANCE", the balance section is placed first.
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
| Zero-weight sets | `weight_kg == 0` | Valid (bodyweight exercises — e.g. Pull-Up in sample data); included in volume as 0 kg; excluded from `max_weight_kg`; context notes "[bodyweight — reps only]" |
| Deload week | `>20% volume drop vs 4-week avg` | Not flagged as negative trend; listed in `--- DELOAD WEEKS ---` section; LLM instructed to treat as intentional recovery |
| Mixed units | Same exercise with `"lb"` then `"kg"` (User B) | Both normalised to kg at insert; analytics always uses `weight_kg` — no apparent weight drop in normalised data |
| Warmup sets | `is_warmup = True` | Excluded from `max_weight_kg` and trend calculations; included in total volume with a note |
| Future dates | `date > today` | Logged warning at insert; analytics treats them as any other date |

---

## Testing

Analytics functions are **pure Python** — no DB, no LLM, no async. Test directly:

```python
# tests/mock/test_workout.py — analytics section

def test_lb_unit_normalized():
    # User B uses "lb" — 110 lb Bench Press = 49.9 kg
    assert normalize_weight(110, "lb") == pytest.approx(49.9, rel=0.01)

def test_lb_alias_accepted():
    # Both "lb" and "lbs" must be accepted
    assert normalize_weight(45, "lbs") == pytest.approx(20.41, rel=0.01)

def test_pull_up_bodyweight_zero_weight():
    # Pull-Up sets (weight=0, unit="kg") are valid; volume = 0; excluded from max_weight
    sets = [SetStats(reps=10, weight_kg=Decimal("0"), is_warmup=False),
            SetStats(reps=9,  weight_kg=Decimal("0"), is_warmup=False)]
    assert compute_session_volume(sets) == Decimal("0")

def test_classify_pull_up_hyphenated():
    # "Pull-Up" (exact sample-data form) must map to "back"
    assert classify_exercise("Pull-Up") == "back"

def test_classify_face_pull():
    assert classify_exercise("Face Pull") == "back"

def test_classify_romanian_deadlift_not_confused_with_deadlift():
    assert classify_exercise("Romanian Deadlift") == "legs"
    assert classify_exercise("Deadlift") == "back"

def test_classify_incline_dumbbell_press():
    assert classify_exercise("Incline Dumbbell Press") == "chest"

def test_trend_positive():
    dates   = [date(2026, 2,  2), date(2026, 2,  9)]   # Wk 6 → Wk 7
    volumes = [Decimal("2000"),   Decimal("2200")]
    assert compute_weekly_trend(dates, volumes) == pytest.approx(10.0)

def test_deload_week_detected():
    # User A Jan 27-29 (ISO week 5): volume drops ~26% vs 4-week avg
    dates = [
        date(2026, 1,  5), date(2026, 1,  8), date(2026, 1, 10),  # Wk 2
        date(2026, 1, 12), date(2026, 1, 15), date(2026, 1, 17),  # Wk 3
        date(2026, 1, 19), date(2026, 1, 22), date(2026, 1, 24),  # Wk 4
        date(2026, 1, 26), date(2026, 1, 27),                     # Wk 5 (deload)
    ]
    volumes = [
        Decimal("2800"), Decimal("3200"), Decimal("2600"),   # Wk 2
        Decimal("2900"), Decimal("3400"), Decimal("2700"),   # Wk 3
        Decimal("3000"), Decimal("3300"), Decimal("2800"),   # Wk 4
        Decimal("2000"), Decimal("1900"),                    # Wk 5 — deload
    ]
    deloads = detect_deload_weeks(dates, volumes)
    assert "2026-W05" in deloads

def test_deload_not_flagged_as_trend_decline():
    # Weeks adjacent to a deload week must not produce negative trend
    ...  # integration test: deload week is in deload_weeks, not in a negative ExerciseStats trend

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
