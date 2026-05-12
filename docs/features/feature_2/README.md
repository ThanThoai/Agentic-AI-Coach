# Feature 2 — Workout History Analysis

**Version:** v1.0 | **Status:** Planned | **Last updated:** 2026-05-12

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

## Component docs

| File | Scope |
|------|-------|
| [database.md](./database.md) | Schema design, SQLAlchemy models, Alembic migrations, indexes, user isolation guarantee |
| [analytics.md](./analytics.md) | Python analytics engine — unit normalisation, exercise catalog, volume/trend/balance/neglect computations, `AnalysisSummary` |
| [llm-analysis.md](./llm-analysis.md) | Question understanding, structured context format, prompt design, generation, answer validation |

---

## System architecture

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CRUD — workout session management
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST   /api/v1/workout/sessions        → create session + exercises + sets
  GET    /api/v1/workout/sessions        → paginated list (cursor by date)
  GET    /api/v1/workout/sessions/{id}   → session detail with exercises + sets
  PATCH  /api/v1/workout/sessions/{id}   → update notes / exercises
  DELETE /api/v1/workout/sessions/{id}   → soft-delete (sets deleted_at)


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
    (SQL: SELECT ... WHERE user_id = ? — enforces isolation at DB level)
          │
          │  0 sessions → early return "No workout history found."
          ▼
    normalize_units()        →  all weights converted to kg
          │
          ▼  analyzer.py
    compute_analytics()      →  AnalysisSummary
      ├─ session_volume()    →  per-session total (sets × reps × kg)
      ├─ exercise_trends()   →  week-over-week progression per exercise
      ├─ muscle_frequency()  →  sessions per muscle group per week
      ├─ balance_ratio()     →  push/pull + chest/back volume ratio
      ├─ neglect_check()     →  muscles not trained in > 14 days
      └─ peak_performance()  →  max weight + best set per exercise
          │
          │  < 2 sessions → mark insufficient_data=True in summary
          ▼
    build_llm_context()      →  structured text block (NOT raw JSON)
          │
          ▼  prompts/workout.py
    LLM call  (Sonnet — coaching quality, temperature=0.3, max_tokens=600)
    → plain markdown answer referencing specific numbers
          │
          ▼
    WorkoutAnalysisResponse { answer, data_summary, model, usage }
```

---

## Key design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| History storage | PostgreSQL (relational) | Analytics queries (GROUP BY, SUM, trend joins) are far cheaper with proper columns than with JSONB blobs |
| Weight storage | Always `NUMERIC(6,2)` in kg | Normalise at API boundary; analytics never deal with mixed units |
| Exercise name | Free-text, not FK | Users enter "Paused squat", "Close-grip bench" — a rigid catalog FK would reject legitimate entries |
| Muscle group | Denormalised at insert | Avoids O(N) catalog lookups on every analytics query; stored as a column after catalog classification at write time |
| Pre-LLM analytics | Pure Python, no LLM | Volume, trends, frequency are deterministic calculations — sending raw data to LLM is expensive, slow, and hallucination-prone |
| LLM context format | Structured text summary | "Bench Press: 3 sessions, avg volume 2 100 kg, +8% last week" is far safer than a 500-entry JSON array |
| User isolation | `WHERE user_id = ?` in every DB query | Enforced at the repository layer — no application-level filtering that could be accidentally skipped |
| Soft deletes | `deleted_at TIMESTAMPTZ` on sessions | Preserves data for recovery; cascade-hidden at query layer |
| Insufficient data | Acknowledged in context, not rejected | "Only 1 session" is valid data — the LLM is told to caveat its answer, not the API to return an error |

---

## File layout

```
backend/app/
├── models/
│   └── workout.py              WorkoutSession, WorkoutExercise, WorkoutSet ORM models
├── schemas/
│   └── workout.py              Pydantic request / response schemas
├── repositories/
│   └── workout.py              WorkoutRepository — all DB queries
├── services/
│   └── workout.py              WorkoutService — orchestration (fetch → analyse → LLM)
├── workout/
│   ├── __init__.py
│   ├── normalizer.py           Unit conversion (lbs → kg); validate reps/weight ranges
│   ├── catalog.py              Exercise → muscle group mapping; fuzzy match
│   └── analyzer.py             Analytics engine; AnalysisSummary dataclass; context builder
├── prompts/
│   └── workout.py              WORKOUT_ANALYSIS_SYSTEM prompt
└── api/v1/
    └── workout.py              Route handlers for CRUD + analyze endpoints

backend/tests/mock/
└── test_workout.py             Analytics unit tests; endpoint tests; data isolation test

backend/alembic/versions/
└── xxxx_add_workout_tables.py  Migration: workout_sessions, workout_exercises, workout_sets
```

---

## API contract

### Create session

```json
POST /api/v1/workout/sessions
Authorization: Bearer <token>

{
  "date": "2026-03-20",
  "notes": "Felt strong today",
  "exercises": [
    {
      "name": "Bench Press",
      "order_index": 1,
      "sets": [
        { "set_number": 1, "reps": 10, "weight": 80, "unit": "kg" },
        { "set_number": 2, "reps": 8,  "weight": 85, "unit": "kg" },
        { "set_number": 3, "reps": 6,  "weight": 90, "unit": "kg" }
      ]
    }
  ]
}
```

Response `201`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "date": "2026-03-20",
  "notes": "Felt strong today",
  "exercises": [ ... ],
  "created_at": "2026-03-20T09:00:00Z"
}
```

---

### Analyse history

```json
POST /api/v1/workout/analyze
Authorization: Bearer <token>

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
| `date_to` | `date` | ISO-8601; defaults to today; must be ≥ date_from |

Response `200`:
```json
{
  "answer": "Over the last month your Bench Press has shown clear progression...",
  "data_summary": {
    "sessions_analysed": 12,
    "date_range": { "from": "2026-04-12", "to": "2026-05-12" },
    "exercises_found": 8,
    "muscle_groups_found": ["chest", "back", "legs", "shoulders"],
    "insufficient_data": false
  },
  "model": "anthropic/claude-sonnet-4-5",
  "usage": { "prompt_tokens": 620, "completion_tokens": 280, "total_tokens": 900 }
}
```

---

## Open questions

1. **Question classifier** — Should a fast Haiku call pre-classify the question type (trend / balance / plan) before building context, so only the relevant analytics slice is included? This would reduce prompt size for targeted questions.
2. **Plan generation** — "Suggest a workout plan for next week" requires generative output beyond summarising history. Decide if this is in scope or deferred to Feature 3.
3. **Trend window** — The default 90-day window may be too long for beginners (few sessions) and too short for annual periodisation tracking. Consider user-configurable defaults.
4. **Exercise name normalisation** — "Bench" / "Bench Press" / "Barbell Bench Press" should group as one exercise. A fuzzy-match step at insert time would help; evaluate tradeoff vs. surprising the user by silently renaming their entry.
5. **Pagination of analyze** — If a user has 3 years of history, fetching all sessions for analysis is expensive. Consider a hard cap (e.g. 500 sessions) and surface it in `data_summary`.
