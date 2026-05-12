"""Exercise catalog: maps exercise names to muscle groups.

Classification strategy:
1. Exact match (case-insensitive, stripped)
2. Substring longest-match: find all catalog keys that are substrings of the
   query; return the muscle group of the longest one.
3. Fallback: "unknown"
"""

from __future__ import annotations

# Maps lowercase exercise name → muscle group string
EXERCISE_CATALOG: dict[str, str] = {
    # ── Back ─────────────────────────────────────────────────────────────────
    "pull-up": "back",
    "pull up": "back",
    "chin-up": "back",
    "chin up": "back",
    "pulldown": "back",
    "lat pulldown": "back",
    "seated cable row": "back",
    "cable row": "back",
    "bent over row": "back",
    "barbell row": "back",
    "dumbbell row": "back",
    "t-bar row": "back",
    "t bar row": "back",
    "pendlay row": "back",
    "chest-supported row": "back",
    "chest supported row": "back",
    "face pull": "back",
    "deadlift": "back",
    "rack pull": "back",
    "shrug": "back",
    "barbell shrug": "back",
    "dumbbell shrug": "back",
    "hyperextension": "back",
    "back extension": "back",
    "good morning": "back",
    # ── Legs ──────────────────────────────────────────────────────────────────
    "squat": "legs",
    "back squat": "legs",
    "front squat": "legs",
    "goblet squat": "legs",
    "hack squat": "legs",
    "bulgarian split squat": "legs",
    "split squat": "legs",
    "leg press": "legs",
    "lunge": "legs",
    "walking lunge": "legs",
    "reverse lunge": "legs",
    "romanian deadlift": "legs",
    "rdl": "legs",
    "stiff leg deadlift": "legs",
    "leg curl": "legs",
    "lying leg curl": "legs",
    "seated leg curl": "legs",
    "leg extension": "legs",
    "calf raise": "legs",
    "standing calf raise": "legs",
    "seated calf raise": "legs",
    "hip thrust": "legs",
    "glute bridge": "legs",
    "step up": "legs",
    "box jump": "legs",
    "sumo deadlift": "legs",
    # ── Chest ─────────────────────────────────────────────────────────────────
    "bench press": "chest",
    "barbell bench press": "chest",
    "dumbbell bench press": "chest",
    "flat bench press": "chest",
    "incline bench press": "chest",
    "incline barbell press": "chest",
    "incline dumbbell press": "chest",
    "decline bench press": "chest",
    "decline dumbbell press": "chest",
    "chest fly": "chest",
    "dumbbell fly": "chest",
    "cable fly": "chest",
    "cable crossover": "chest",
    "pec deck": "chest",
    "push-up": "chest",
    "push up": "chest",
    "dip": "chest",
    "chest dip": "chest",
    # ── Shoulders ─────────────────────────────────────────────────────────────
    "overhead press": "shoulders",
    "military press": "shoulders",
    "barbell overhead press": "shoulders",
    "dumbbell overhead press": "shoulders",
    "shoulder press": "shoulders",
    "arnold press": "shoulders",
    "lateral raise": "shoulders",
    "dumbbell lateral raise": "shoulders",
    "cable lateral raise": "shoulders",
    "front raise": "shoulders",
    "rear delt fly": "shoulders",
    "rear delt raise": "shoulders",
    "upright row": "shoulders",
    "landmine press": "shoulders",
    # ── Arms ──────────────────────────────────────────────────────────────────
    "bicep curl": "arms",
    "biceps curl": "arms",
    "barbell curl": "arms",
    "dumbbell curl": "arms",
    "hammer curl": "arms",
    "concentration curl": "arms",
    "preacher curl": "arms",
    "ez bar curl": "arms",
    "cable curl": "arms",
    "incline curl": "arms",
    "spider curl": "arms",
    "tricep pushdown": "arms",
    "triceps pushdown": "arms",
    "cable pushdown": "arms",
    "tricep extension": "arms",
    "triceps extension": "arms",
    "skull crusher": "arms",
    "close grip bench press": "arms",
    "overhead tricep extension": "arms",
    "tricep dip": "arms",
    "rope pushdown": "arms",
    "rope extension": "arms",
    # ── Core ──────────────────────────────────────────────────────────────────
    "plank": "core",
    "crunch": "core",
    "sit-up": "core",
    "sit up": "core",
    "ab wheel": "core",
    "cable crunch": "core",
    "hanging leg raise": "core",
    "leg raise": "core",
    "russian twist": "core",
    "pallof press": "core",
    "dead bug": "core",
    "hollow body hold": "core",
    # ── Cardio / Full Body ────────────────────────────────────────────────────
    "clean": "full body",
    "power clean": "full body",
    "hang clean": "full body",
    "snatch": "full body",
    "thruster": "full body",
    "kettlebell swing": "full body",
    "burpee": "full body",
    "farmer carry": "full body",
    "farmer walk": "full body",
    "sled push": "full body",
    "sled pull": "full body",
    "battle rope": "cardio",
    "row machine": "cardio",
    "treadmill": "cardio",
    "bike": "cardio",
    "cycling": "cardio",
    "elliptical": "cardio",
    "stair climber": "cardio",
}

# Muscle group category sets for ratio calculations
PUSH_GROUPS: frozenset[str] = frozenset({"chest", "shoulders", "arms"})
PULL_GROUPS: frozenset[str] = frozenset({"back"})


def classify_muscle_group(exercise_name: str) -> str:
    """Return the muscle group for an exercise name.

    Lookup order:
    1. Exact match (case-insensitive, stripped)
    2. Substring longest-match: return the muscle group of the longest catalog
       key that appears as a substring in the query.
    3. Fallback: "unknown"
    """
    normalised = exercise_name.strip().lower()

    # 1. Exact match
    if normalised in EXERCISE_CATALOG:
        return EXERCISE_CATALOG[normalised]

    # 2. Substring longest match
    best_key: str | None = None
    best_len: int = 0
    for key in EXERCISE_CATALOG:
        if key in normalised and len(key) > best_len:
            best_key = key
            best_len = len(key)

    if best_key is not None:
        return EXERCISE_CATALOG[best_key]

    # 3. Fallback
    return "unknown"
