# Workout Tracking

**Version:** v1.0 | **Status:** Specced | **Last updated:** 2026-05-11

## Problem

Users need a structured way to log workouts so the AI coach has accurate historical data to analyse.

## User stories

- As a user, I can log a workout session with one or more exercises.
- As a user, each exercise has sets with reps, weight, and optional RPE/RIR.
- As a user, I can view my workout history sorted by date.
- As a user, weights are stored in kg regardless of what unit I enter.

## Data model

```
Workout
  id          UUID PK
  user_id     UUID FK → users
  date        DATE
  notes       TEXT nullable
  created_at  TIMESTAMPTZ
  deleted_at  TIMESTAMPTZ nullable   # soft delete

WorkoutSet
  id          UUID PK
  workout_id  UUID FK → workouts
  exercise    VARCHAR(200)
  reps        SMALLINT
  weight_kg   FLOAT                  # always kg, normalized at write time
  rpe         FLOAT nullable         # 6.0 – 10.0
  rir         SMALLINT nullable      # 0 – 5
  created_at  TIMESTAMPTZ
```

## API

```
POST   /api/v1/workouts                  Create workout + sets
GET    /api/v1/workouts?from=&to=        List (cursor paginated, 20/page)
GET    /api/v1/workouts/{id}             Single workout with sets
PUT    /api/v1/workouts/{id}             Update notes only
DELETE /api/v1/workouts/{id}            Soft delete
```

## Unit normalization

Weight input in `lbs` is converted to `kg` before storage:
`kg = lbs × 0.453592`

The response always returns `weight_kg`. Frontend renders in the user's preferred unit (stored in user profile).

## Validation rules

- `exercise` — 1–200 chars, required
- `reps` — 1–100
- `weight_kg` — 0–1000 (0 = bodyweight)
- `rpe` — 6.0–10.0 (step 0.5), optional
- `rir` — 0–5, optional
- At least 1 set per workout
- Max 30 sets per workout
