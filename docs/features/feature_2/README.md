# Feature 2 — Workout History Analysis

**Version:** v1.1 | **Status:** Planned | **Last updated:** 2026-05-12

---

## Requirement

> Build an endpoint that accepts a user's workout history and a natural language question,
> then returns an AI-generated insight backed by real numbers from the data.
>
> The system must:
> - Parse and analyse workout data **before** passing to the LLM — never dump raw JSON into the prompt
> - Provide data-backed responses that reference specific numbers, dates, and trends
> - Handle edge cases: empty history, insufficient data, unknown exercises
> - Maintain user data isolation — User A's history must never appear in User B's context or response

---

## Sample data

`sample-data/workout-history.json` contains two reference users over Jan–Mar 2026:

| User | Profile | Key characteristics |
|------|---------|-------------------|
| **User A (Alex)** | Intermediate, PPL split | Consistent progressive overload (+17% bench/squat over 3 months), deload week Jan 27-29, bodyweight Pull-Ups |
| **User B (Binh)** | Beginner-intermediate | Chest-dominant (bench press every session), only 2 squat sessions in 3 months, no deadlift, mixes `lb`/`kg` units |

---

## Component docs

| File | Scope |
|------|-------|
| [database.md](./database.md) | Schema design, SQLAlchemy models, Alembic migrations, indexes, user isolation guarantee |
| [analytics.md](./analytics.md) | Python analytics engine — unit normalisation, exercise catalog, volume/trend/balance/neglect/deload computations, `AnalysisSummary` |
| [llm-analysis.md](./llm-analysis.md) | Question understanding, structured context format, prompt design, generation, answer validation |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CRUD — workout data ingestion
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/workout/log
  Body: array of flat exercise entries  { date, exercise, sets[] }
          │
          ▼  normalizer.py
    normalize_weight(weight, unit)  →  all weights to kg
    (handles "kg" and "lb"; zero-weight for bodyweight exercises)
          │
          ▼  catalog.py
    classify_exercise(name)  →  muscle_group
          │
          ▼  service layer
    group_entries_by_date()  →  sessions dict  { "2026-01-02": [exercise…] }
          │
          ▼  WorkoutRepository
    upsert sessions + exercises + sets  →  PostgreSQL


  GET    /api/v1/workout/sessions          → paginated list (cursor by date)
  GET    /api/v1/workout/sessions/{id}     → session detail
  PATCH  /api/v1/workout/sessions/{id}     → update notes
  DELETE /api/v1/workout/sessions/{id}     → soft-delete


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONLINE — AI analysis per request
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /api/v1/workout/analyze  { "question": "...", "date_from"?, "date_to"? }
          │
          ▼  Auth middleware
    get_current_user()  →  user_id
          │
          ▼  WorkoutRepository
    fetch_history(user_id, date_from, date_to)
    (SQL: SELECT ... WHERE user_id = ?  — isolation enforced at DB level)
          │
          │  0 sessions → early return "No workout history found."
          ▼
    compute_analytics()      →  AnalysisSummary
      ├─ session_volume()    →  per-session total (sets × reps × kg)
      ├─ exercise_trends()   →  week-over-week progression per exercise
      ├─ muscle_frequency()  →  sessions per muscle group per week
      ├─ balance_ratio()     →  push/pull + chest/back volume ratio
      ├─ neglect_check()     →  muscles not trained in > 14 days
      ├─ peak_performance()  →  max weight + best set per exercise
      └─ detect_deload()     →  weeks with > 20% volume drop
          │
          │  < 2 sessions → mark insufficient_data=True in summary
          ▼
    build_llm_context()      →  structured text block (NOT raw JSON)
          │
          ▼  LLM call  (Sonnet, temperature=0.3, max_tokens=600)
    → plain markdown answer referencing specific numbers
          │
          ▼
    WorkoutAnalysisResponse { answer, data_summary, model, usage }
```

---

## Key design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| API input format | Flat per-exercise entries `{date, exercise, sets[]}` | Matches the spec format and how users naturally log (one exercise at a time); service groups by date |
| Session grouping | Service layer groups entries with the same date | Keeps input simple; a "session" is an application concept, not a user concept |
| Weight storage | Always `NUMERIC(6,2)` in kg | Normalise at API boundary; analytics never deal with mixed units |
| Unit values accepted | `"kg"` and `"lb"` (case-insensitive) | Sample data uses `"lb"` not `"lbs"` — handle both; reject anything else |
| Zero-weight entries | Stored as `0.00 kg`, labelled bodyweight | Pull-Ups with weight=0 are valid; excluded from max-weight rankings |
| Exercise name | Free-text, not FK | Users enter "Pull-Up", "paused squat" — rigid catalog FK would reject valid entries |
| Muscle group | Denormalised at insert via catalog | Avoids O(N) catalog lookups on every analytics query |
| Pre-LLM analytics | Pure Python, no LLM | Volume, trends, frequency are deterministic — raw data in LLM prompt is expensive and hallucination-prone |
| Deload detection | >20% volume drop vs 4-week average | User A's Jan 27-29 week is a clear deload; must not be flagged as negative trend |
| User isolation | `WHERE user_id = ?` in every DB query | Enforced at repository layer — no application-level filtering that can be skipped |

---

## File layout

```
backend/app/
├── models/
│   └── workout.py              WorkoutSession, WorkoutExercise, WorkoutSet ORM models
├── schemas/
│   └── workout.py              Pydantic request/response schemas
├── repositories/
│   └── workout.py              WorkoutRepository — all DB queries
├── services/
│   └── workout.py              WorkoutService — orchestration (group → normalise → insert / fetch → analyse → LLM)
├── workout/
│   ├── __init__.py
│   ├── normalizer.py           Unit conversion (lb → kg); bodyweight handling; input validation
│   ├── catalog.py              Exercise → muscle group; case-insensitive substring match
│   └── analyzer.py             Analytics engine; deload detection; AnalysisSummary; context builder
├── prompts/
│   └── workout.py              WORKOUT_ANALYSIS_SYSTEM prompt
└── api/v1/
    └── workout.py              Route handlers

backend/tests/mock/
└── test_workout.py             Analytics unit tests; endpoint tests; data isolation test

backend/alembic/versions/
└── xxxx_add_workout_tables.py  Migration: workout_sessions, workout_exercises, workout_sets
```

---

## API contract

### Log workout entries

```http
POST /api/v1/workout/log
Authorization: Bearer <token>
Content-Type: application/json
```

```json
[
  {
    "date": "2026-03-05",
    "exercise": "Bench Press",
    "sets": [
      { "reps": 8, "weight": 80, "unit": "kg" },
      { "reps": 8, "weight": 80, "unit": "kg" },
      { "reps": 7, "weight": 80, "unit": "kg" }
    ]
  },
  {
    "date": "2026-03-05",
    "exercise": "Overhead Press",
    "sets": [
      { "reps": 10, "weight": 45, "unit": "kg" },
      { "reps": 10, "weight": 45, "unit": "kg" }
    ]
  },
  {
    "date": "2026-03-05",
    "exercise": "Pull-Up",
    "sets": [
      { "reps": 10, "weight": 0, "unit": "kg" },
      { "reps": 9,  "weight": 0, "unit": "kg" }
    ]
  }
]
```

| Field | Type | Constraints |
|-------|------|-------------|
| `date` | `string` (ISO-8601) | Required; not in the future (warning logged, not rejected) |
| `exercise` | `string` | 1–100 characters |
| `sets` | `array` | 1–20 sets per exercise |
| `sets[].reps` | `integer` | 1–200 |
| `sets[].weight` | `number` | 0–1 000 (0 = bodyweight) |
| `sets[].unit` | `string` | `"kg"` or `"lb"` (case-insensitive) |

Response `201`:
```json
{
  "sessions_created": 1,
  "entries_logged": 3,
  "date": "2026-03-05"
}
```

---

### Analyse history

```http
POST /api/v1/workout/analyze
Authorization: Bearer <token>
```

```json
{
  "question": "What's my bench press trend over the last month?",
  "date_from": "2026-04-12",
  "date_to": "2026-05-12"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `question` | `string` | 5–500 characters |
| `date_from` | `date` | ISO-8601; defaults to 90 days ago |
| `date_to` | `date` | ISO-8601; defaults to today; must be ≥ `date_from` |

Response `200`:
```json
{
  "answer": "Over the last month your Bench Press has shown clear progression...",
  "data_summary": {
    "sessions_analysed": 12,
    "date_range": { "from": "2026-04-12", "to": "2026-05-12" },
    "exercises_found": 8,
    "muscle_groups_found": ["chest", "back", "legs", "shoulders"],
    "deload_weeks_detected": 0,
    "insufficient_data": false
  },
  "model": "anthropic/claude-sonnet-4-5",
  "usage": { "prompt_tokens": 620, "completion_tokens": 280, "total_tokens": 900 }
}
```

---

## Open questions

1. **Deload vs regression**: The 20% volume drop threshold for deload detection is an estimate. Validate against User A's actual Jan 27-29 data: bench dropped from 75→60kg (-20%), OHP from 42.5→30kg (-29%), squat from 105→80kg (-24%). A 4-week rolling average baseline may be more accurate than single-week comparison.
2. **Exercise name normalisation**: "Bench", "Bench Press", "Barbell Bench Press" should probably group. A fuzzy-match step at insert time helps analytics; evaluate tradeoff vs. surprising the user by renaming their entry silently.
3. **Question classifier cost**: Haiku adds ~150ms. Benchmark whether the context focus improvement justifies the latency for short, targeted questions.
4. **Pagination of analyze**: User A has ~60 entries over 3 months. At 3 years that is ~720 entries — still manageable. Cap at 500 sessions and surface in `data_summary.sessions_analysed`.
5. **User B unit switch**: Bench Press appears as lb (Jan-Feb) then kg (late Feb-Mar) — the same exercise appears to "drop" in weight after normalisation if not handled carefully (110lb ≈ 49.9kg but later recorded as 55-60kg). Trend calculation must use the kg-normalised value throughout; the apparent drop will disappear.
