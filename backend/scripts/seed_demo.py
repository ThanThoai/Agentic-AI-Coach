"""
Seed demo workout data for Alex and Binh.

Usage:
    cd backend
    uv run python -m scripts.seed_demo

Run after: uv run alembic upgrade head
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.workout.catalog import classify_muscle_group
from app.workout.normalizer import normalize_weight

# ── Demo user identities (must match auth.py DEMO_USERS) ────────────────────

ALEX_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BINH_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

# ── Workout data ─────────────────────────────────────────────────────────────
# Each entry: (date_offset_from_today, exercise, [(reps, weight_kg), ...])
# date_offset is negative = N days ago.

TODAY = date(2026, 5, 12)


def d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


# Alex — PPL split (Push/Pull/Leg), 5 days on 2 off, ~3 months of data
# Progressive overload: bench press 75 kg → 92.5 kg over the period
ALEX_SESSIONS: list[tuple[date, list[tuple[str, list[tuple[int, float]]]]]] = [
    # ── Week 13 (May 5–11) ───────────────────────────────────────────────────
    (d(7), [  # May 5 — Push
        ("Bench Press",         [(5, 92.5), (5, 92.5), (4, 92.5)]),
        ("Incline Dumbbell Press", [(10, 32), (9, 32), (8, 32)]),
        ("Lateral Raise",       [(15, 12), (15, 12), (12, 12)]),
        ("Tricep Pushdown",     [(12, 30), (12, 30), (10, 30)]),
    ]),
    (d(6), [  # May 6 — Pull
        ("Pull-up",             [(8, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(3, 140), (3, 140), (3, 140)]),
        ("Face Pull",           [(15, 20), (15, 20), (15, 20)]),
        ("Bicep Curl",          [(12, 16), (12, 16), (10, 16)]),
    ]),
    (d(5), [  # May 7 — Leg
        ("Squat",               [(5, 120), (5, 120), (5, 120)]),
        ("Romanian Deadlift",   [(10, 90), (10, 90), (8, 90)]),
        ("Leg Press",           [(12, 180), (12, 180), (10, 180)]),
    ]),
    (d(3), [  # May 9 — Push
        ("Bench Press",         [(5, 90), (5, 90), (5, 90)]),
        ("Incline Dumbbell Press", [(10, 30), (10, 30), (9, 30)]),
        ("Lateral Raise",       [(15, 12), (15, 12), (15, 12)]),
        ("Tricep Pushdown",     [(12, 27.5), (12, 27.5), (12, 27.5)]),
    ]),
    (d(2), [  # May 10 — Pull
        ("Pull-up",             [(10, 0), (8, 0), (7, 0)]),
        ("Deadlift",            [(3, 137.5), (3, 137.5), (3, 137.5)]),
        ("Face Pull",           [(15, 20), (15, 20), (15, 20)]),
    ]),

    # ── Week 12 (Apr 28 – May 4) ─────────────────────────────────────────────
    (d(14), [  # Apr 28 — Push
        ("Bench Press",         [(5, 90), (5, 90), (4, 90)]),
        ("Incline Dumbbell Press", [(10, 30), (9, 30), (8, 30)]),
        ("Lateral Raise",       [(15, 12), (15, 12), (12, 12)]),
        ("Tricep Pushdown",     [(12, 27.5), (12, 27.5), (10, 27.5)]),
    ]),
    (d(13), [  # Apr 29 — Pull
        ("Pull-up",             [(8, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(3, 135), (3, 135), (3, 135)]),
        ("Face Pull",           [(15, 17.5), (15, 17.5), (15, 17.5)]),
    ]),
    (d(12), [  # Apr 30 — Leg
        ("Squat",               [(5, 117.5), (5, 117.5), (4, 117.5)]),
        ("Romanian Deadlift",   [(10, 87.5), (10, 87.5), (8, 87.5)]),
        ("Leg Press",           [(12, 175), (12, 175), (10, 175)]),
    ]),
    (d(10), [  # May 2 — Push
        ("Bench Press",         [(5, 87.5), (5, 87.5), (5, 87.5)]),
        ("Incline Dumbbell Press", [(10, 28), (10, 28), (9, 28)]),
        ("Lateral Raise",       [(15, 10), (15, 10), (15, 10)]),
    ]),
    (d(9), [  # May 3 — Pull
        ("Pull-up",             [(9, 0), (8, 0), (7, 0)]),
        ("Deadlift",            [(3, 132.5), (3, 132.5), (3, 132.5)]),
        ("Face Pull",           [(15, 17.5), (15, 17.5), (15, 17.5)]),
        ("Bicep Curl",          [(12, 14), (12, 14), (10, 14)]),
    ]),

    # ── Week 11 (Apr 21–27) ──────────────────────────────────────────────────
    (d(21), [  # Apr 21 — Push
        ("Bench Press",         [(5, 87.5), (5, 87.5), (4, 87.5)]),
        ("Incline Dumbbell Press", [(10, 28), (9, 28), (8, 28)]),
        ("Tricep Pushdown",     [(12, 25), (12, 25), (10, 25)]),
    ]),
    (d(20), [  # Apr 22 — Pull
        ("Pull-up",             [(7, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(3, 130), (3, 130), (3, 130)]),
        ("Face Pull",           [(15, 17.5), (15, 17.5), (15, 17.5)]),
    ]),
    (d(19), [  # Apr 23 — Leg
        ("Squat",               [(5, 115), (5, 115), (5, 115)]),
        ("Romanian Deadlift",   [(10, 85), (10, 85), (8, 85)]),
        ("Leg Press",           [(12, 170), (12, 170), (10, 170)]),
    ]),
    (d(17), [  # Apr 25 — Push
        ("Bench Press",         [(5, 85), (5, 85), (5, 85)]),
        ("Incline Dumbbell Press", [(10, 26), (10, 26), (9, 26)]),
        ("Lateral Raise",       [(15, 10), (15, 10), (15, 10)]),
        ("Tricep Pushdown",     [(12, 25), (12, 25), (12, 25)]),
    ]),
    (d(16), [  # Apr 26 — Pull
        ("Pull-up",             [(8, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(5, 127.5), (5, 127.5), (5, 127.5)]),
        ("Face Pull",           [(15, 15), (15, 15), (15, 15)]),
    ]),

    # ── Week 10 (Apr 14–20) — Deload week ────────────────────────────────────
    (d(28), [  # Apr 14 — Push (deload: ~60% volume)
        ("Bench Press",         [(5, 75), (5, 75)]),
        ("Incline Dumbbell Press", [(8, 22), (8, 22)]),
    ]),
    (d(27), [  # Apr 15 — Pull (deload)
        ("Pull-up",             [(5, 0), (5, 0)]),
        ("Deadlift",            [(3, 100), (3, 100)]),
    ]),
    (d(25), [  # Apr 17 — Leg (deload)
        ("Squat",               [(5, 90), (5, 90)]),
        ("Leg Press",           [(10, 130), (10, 130)]),
    ]),

    # ── Week 9 (Apr 7–13) ────────────────────────────────────────────────────
    (d(35), [  # Apr 7 — Push
        ("Bench Press",         [(5, 85), (5, 85), (4, 85)]),
        ("Incline Dumbbell Press", [(10, 26), (9, 26), (8, 26)]),
        ("Lateral Raise",       [(15, 10), (15, 10), (12, 10)]),
        ("Tricep Pushdown",     [(12, 25), (12, 25), (10, 25)]),
    ]),
    (d(34), [  # Apr 8 — Pull
        ("Pull-up",             [(8, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(3, 125), (3, 125), (3, 125)]),
        ("Face Pull",           [(15, 15), (15, 15), (15, 15)]),
    ]),
    (d(33), [  # Apr 9 — Leg
        ("Squat",               [(5, 112.5), (5, 112.5), (5, 112.5)]),
        ("Romanian Deadlift",   [(10, 82.5), (10, 82.5), (8, 82.5)]),
        ("Leg Press",           [(12, 165), (12, 165), (10, 165)]),
    ]),
    (d(31), [  # Apr 11 — Push
        ("Bench Press",         [(5, 82.5), (5, 82.5), (5, 82.5)]),
        ("Incline Dumbbell Press", [(10, 24), (10, 24), (9, 24)]),
        ("Tricep Pushdown",     [(12, 22.5), (12, 22.5), (12, 22.5)]),
    ]),

    # ── Week 8 (Mar 31 – Apr 6) ──────────────────────────────────────────────
    (d(42), [  # Mar 31 — Push
        ("Bench Press",         [(5, 82.5), (5, 82.5), (4, 82.5)]),
        ("Incline Dumbbell Press", [(10, 24), (9, 24), (8, 24)]),
        ("Lateral Raise",       [(15, 10), (15, 10), (12, 10)]),
        ("Tricep Pushdown",     [(12, 22.5), (12, 22.5), (10, 22.5)]),
    ]),
    (d(41), [  # Apr 1 — Pull
        ("Pull-up",             [(7, 0), (6, 0), (6, 0)]),
        ("Deadlift",            [(3, 122.5), (3, 122.5), (3, 122.5)]),
        ("Face Pull",           [(15, 15), (15, 15), (15, 15)]),
        ("Bicep Curl",          [(12, 12), (12, 12), (10, 12)]),
    ]),
    (d(40), [  # Apr 2 — Leg
        ("Squat",               [(5, 110), (5, 110), (5, 110)]),
        ("Romanian Deadlift",   [(10, 80), (10, 80), (8, 80)]),
        ("Leg Press",           [(12, 160), (12, 160), (10, 160)]),
    ]),
    (d(38), [  # Apr 4 — Push
        ("Bench Press",         [(5, 80), (5, 80), (5, 80)]),
        ("Incline Dumbbell Press", [(10, 22), (10, 22), (9, 22)]),
        ("Lateral Raise",       [(15, 8), (15, 8), (15, 8)]),
    ]),

    # ── Week 7 (Mar 24–30) ───────────────────────────────────────────────────
    (d(49), [  # Mar 24 — Pull
        ("Pull-up",             [(7, 0), (6, 0), (5, 0)]),
        ("Deadlift",            [(3, 120), (3, 120), (3, 120)]),
        ("Face Pull",           [(15, 12.5), (15, 12.5), (15, 12.5)]),
    ]),
    (d(48), [  # Mar 25 — Leg
        ("Squat",               [(5, 107.5), (5, 107.5), (4, 107.5)]),
        ("Romanian Deadlift",   [(10, 77.5), (10, 77.5), (8, 77.5)]),
        ("Leg Press",           [(12, 155), (12, 155), (10, 155)]),
    ]),
    (d(46), [  # Mar 27 — Push
        ("Bench Press",         [(5, 80), (5, 80), (4, 80)]),
        ("Incline Dumbbell Press", [(10, 22), (9, 22), (8, 22)]),
        ("Tricep Pushdown",     [(12, 20), (12, 20), (10, 20)]),
    ]),
    (d(45), [  # Mar 28 — Pull
        ("Pull-up",             [(8, 0), (7, 0), (6, 0)]),
        ("Deadlift",            [(5, 117.5), (5, 117.5), (5, 117.5)]),
        ("Face Pull",           [(15, 12.5), (15, 12.5), (15, 12.5)]),
        ("Bicep Curl",          [(12, 12), (12, 12), (10, 12)]),
    ]),

    # ── Week 6 (Mar 17–23) ───────────────────────────────────────────────────
    (d(56), [  # Mar 17 — Push
        ("Bench Press",         [(5, 77.5), (5, 77.5), (4, 77.5)]),
        ("Incline Dumbbell Press", [(10, 20), (9, 20), (8, 20)]),
        ("Lateral Raise",       [(15, 8), (15, 8), (12, 8)]),
        ("Tricep Pushdown",     [(12, 20), (12, 20), (10, 20)]),
    ]),
    (d(55), [  # Mar 18 — Pull
        ("Pull-up",             [(6, 0), (6, 0), (5, 0)]),
        ("Deadlift",            [(3, 115), (3, 115), (3, 115)]),
        ("Face Pull",           [(15, 12.5), (15, 12.5), (15, 12.5)]),
    ]),
    (d(53), [  # Mar 20 — Leg
        ("Squat",               [(5, 105), (5, 105), (5, 105)]),
        ("Romanian Deadlift",   [(10, 75), (10, 75), (8, 75)]),
        ("Leg Press",           [(12, 150), (12, 150), (10, 150)]),
    ]),
    (d(52), [  # Mar 21 — Push
        ("Bench Press",         [(5, 77.5), (5, 77.5), (5, 77.5)]),
        ("Incline Dumbbell Press", [(10, 20), (10, 20), (9, 20)]),
        ("Tricep Pushdown",     [(12, 17.5), (12, 17.5), (12, 17.5)]),
    ]),

    # ── Week 5 (Mar 10–16) ───────────────────────────────────────────────────
    (d(63), [  # Mar 10 — Push
        ("Bench Press",         [(5, 75), (5, 75), (4, 75)]),
        ("Incline Dumbbell Press", [(10, 18), (9, 18), (8, 18)]),
        ("Lateral Raise",       [(15, 8), (15, 8), (12, 8)]),
    ]),
    (d(62), [  # Mar 11 — Pull
        ("Pull-up",             [(6, 0), (5, 0), (5, 0)]),
        ("Deadlift",            [(3, 112.5), (3, 112.5), (3, 112.5)]),
        ("Face Pull",           [(15, 10), (15, 10), (15, 10)]),
    ]),
    (d(60), [  # Mar 13 — Leg
        ("Squat",               [(5, 102.5), (5, 102.5), (4, 102.5)]),
        ("Romanian Deadlift",   [(10, 72.5), (10, 72.5), (8, 72.5)]),
        ("Leg Press",           [(12, 145), (12, 145), (10, 145)]),
    ]),
    (d(59), [  # Mar 14 — Push
        ("Bench Press",         [(5, 75), (5, 75), (5, 75)]),
        ("Incline Dumbbell Press", [(10, 18), (10, 18), (9, 18)]),
        ("Tricep Pushdown",     [(12, 17.5), (12, 17.5), (12, 17.5)]),
    ]),

    # ── Week 4 (Mar 3–9) ─────────────────────────────────────────────────────
    (d(70), [  # Mar 3 — Push
        ("Bench Press",         [(8, 72.5), (8, 72.5), (6, 72.5)]),
        ("Incline Dumbbell Press", [(12, 18), (10, 18), (8, 18)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(69), [  # Mar 4 — Pull
        ("Pull-up",             [(5, 0), (5, 0), (5, 0)]),
        ("Deadlift",            [(5, 110), (5, 110), (5, 110)]),
        ("Face Pull",           [(15, 10), (15, 10), (15, 10)]),
    ]),
    (d(67), [  # Mar 6 — Leg
        ("Squat",               [(5, 100), (5, 100), (5, 100)]),
        ("Romanian Deadlift",   [(10, 70), (10, 70), (8, 70)]),
        ("Leg Press",           [(12, 140), (12, 140), (10, 140)]),
    ]),
    (d(66), [  # Mar 7 — Push
        ("Bench Press",         [(8, 72.5), (7, 72.5), (6, 72.5)]),
        ("Incline Dumbbell Press", [(10, 16), (10, 16), (9, 16)]),
    ]),

    # ── Week 3 (Feb 24 – Mar 2) ──────────────────────────────────────────────
    (d(77), [  # Feb 24 — Pull
        ("Pull-up",             [(5, 0), (4, 0), (4, 0)]),
        ("Deadlift",            [(5, 107.5), (5, 107.5), (5, 107.5)]),
        ("Face Pull",           [(15, 10), (15, 10), (15, 10)]),
    ]),
    (d(76), [  # Feb 25 — Leg
        ("Squat",               [(5, 97.5), (5, 97.5), (4, 97.5)]),
        ("Romanian Deadlift",   [(10, 67.5), (10, 67.5), (8, 67.5)]),
        ("Leg Press",           [(12, 135), (12, 135), (10, 135)]),
    ]),
    (d(74), [  # Feb 27 — Push
        ("Bench Press",         [(8, 70), (8, 70), (6, 70)]),
        ("Incline Dumbbell Press", [(12, 16), (10, 16), (8, 16)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
        ("Tricep Pushdown",     [(12, 15), (12, 15), (10, 15)]),
    ]),
    (d(73), [  # Feb 28 — Pull
        ("Pull-up",             [(5, 0), (5, 0), (4, 0)]),
        ("Deadlift",            [(5, 105), (5, 105), (5, 105)]),
        ("Face Pull",           [(12, 10), (12, 10), (12, 10)]),
    ]),

    # ── Week 2 (Feb 17–23) ───────────────────────────────────────────────────
    (d(84), [  # Feb 17 — Push
        ("Bench Press",         [(8, 67.5), (8, 67.5), (6, 67.5)]),
        ("Incline Dumbbell Press", [(12, 14), (10, 14), (8, 14)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(83), [  # Feb 18 — Pull
        ("Pull-up",             [(4, 0), (4, 0), (3, 0)]),
        ("Deadlift",            [(5, 102.5), (5, 102.5), (5, 102.5)]),
        ("Face Pull",           [(12, 10), (12, 10), (12, 10)]),
    ]),
    (d(81), [  # Feb 20 — Leg
        ("Squat",               [(5, 95), (5, 95), (4, 95)]),
        ("Romanian Deadlift",   [(10, 65), (10, 65), (8, 65)]),
        ("Leg Press",           [(12, 130), (12, 130), (10, 130)]),
    ]),
    (d(80), [  # Feb 21 — Push
        ("Bench Press",         [(8, 67.5), (7, 67.5), (6, 67.5)]),
        ("Incline Dumbbell Press", [(10, 14), (10, 14), (9, 14)]),
        ("Tricep Pushdown",     [(12, 15), (12, 15), (10, 15)]),
    ]),

    # ── Week 1 (Feb 10–16) ───────────────────────────────────────────────────
    (d(91), [  # Feb 10 — Push
        ("Bench Press",         [(10, 65), (8, 65), (6, 65)]),
        ("Incline Dumbbell Press", [(12, 12), (10, 12), (8, 12)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(90), [  # Feb 11 — Pull
        ("Pull-up",             [(4, 0), (4, 0), (3, 0)]),
        ("Deadlift",            [(5, 100), (5, 100), (5, 100)]),
        ("Face Pull",           [(12, 7.5), (12, 7.5), (12, 7.5)]),
    ]),
    (d(88), [  # Feb 13 — Leg
        ("Squat",               [(5, 92.5), (5, 92.5), (4, 92.5)]),
        ("Romanian Deadlift",   [(10, 62.5), (10, 62.5), (8, 62.5)]),
        ("Leg Press",           [(12, 125), (12, 125), (10, 125)]),
    ]),
    (d(87), [  # Feb 14 — Push
        ("Bench Press",         [(10, 65), (8, 65), (6, 65)]),
        ("Incline Dumbbell Press", [(10, 12), (10, 12), (8, 12)]),
    ]),
]

# Binh — Upper/Lower split, 3-4 sessions/week, different focus
BINH_SESSIONS: list[tuple[date, list[tuple[str, list[tuple[int, float]]]]]] = [
    # Week 13
    (d(7), [  # May 5 — Upper
        ("Bench Press",         [(8, 60), (8, 60), (6, 60)]),
        ("Pull-up",             [(6, 0), (5, 0), (5, 0)]),
        ("Lateral Raise",       [(15, 8), (15, 8), (12, 8)]),
        ("Bicep Curl",          [(12, 10), (12, 10), (10, 10)]),
    ]),
    (d(5), [  # May 7 — Lower
        ("Squat",               [(8, 80), (8, 80), (6, 80)]),
        ("Romanian Deadlift",   [(10, 60), (10, 60), (8, 60)]),
        ("Leg Press",           [(12, 120), (12, 120), (10, 120)]),
    ]),
    (d(3), [  # May 9 — Upper
        ("Bench Press",         [(8, 62.5), (7, 62.5), (6, 62.5)]),
        ("Pull-up",             [(6, 0), (6, 0), (5, 0)]),
        ("Bicep Curl",          [(12, 10), (12, 10), (10, 10)]),
    ]),

    # Week 12
    (d(14), [  # Apr 28 — Upper
        ("Bench Press",         [(8, 57.5), (8, 57.5), (6, 57.5)]),
        ("Pull-up",             [(6, 0), (5, 0), (4, 0)]),
        ("Lateral Raise",       [(15, 8), (15, 8), (12, 8)]),
    ]),
    (d(12), [  # Apr 30 — Lower
        ("Squat",               [(8, 77.5), (8, 77.5), (6, 77.5)]),
        ("Leg Press",           [(12, 115), (12, 115), (10, 115)]),
    ]),
    (d(10), [  # May 2 — Upper
        ("Bench Press",         [(8, 57.5), (7, 57.5), (6, 57.5)]),
        ("Pull-up",             [(7, 0), (6, 0), (5, 0)]),
        ("Bicep Curl",          [(12, 10), (12, 10), (10, 10)]),
        ("Tricep Pushdown",     [(12, 17.5), (12, 17.5), (10, 17.5)]),
    ]),

    # Week 11
    (d(21), [  # Apr 21 — Upper
        ("Bench Press",         [(8, 55), (8, 55), (6, 55)]),
        ("Pull-up",             [(5, 0), (5, 0), (4, 0)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(19), [  # Apr 23 — Lower
        ("Squat",               [(8, 75), (8, 75), (6, 75)]),
        ("Romanian Deadlift",   [(10, 57.5), (10, 57.5), (8, 57.5)]),
        ("Leg Press",           [(12, 110), (12, 110), (10, 110)]),
    ]),
    (d(17), [  # Apr 25 — Upper
        ("Bench Press",         [(8, 55), (7, 55), (6, 55)]),
        ("Pull-up",             [(6, 0), (5, 0), (5, 0)]),
        ("Bicep Curl",          [(12, 10), (12, 10), (10, 10)]),
    ]),

    # Week 10 (deload-ish, only 2 sessions)
    (d(28), [  # Apr 14 — Upper
        ("Bench Press",         [(8, 47.5), (8, 47.5)]),
        ("Pull-up",             [(5, 0), (5, 0)]),
    ]),
    (d(26), [  # Apr 16 — Lower
        ("Squat",               [(8, 60), (8, 60)]),
        ("Leg Press",           [(10, 90), (10, 90)]),
    ]),

    # Week 9
    (d(35), [  # Apr 7 — Upper
        ("Bench Press",         [(8, 52.5), (8, 52.5), (6, 52.5)]),
        ("Pull-up",             [(5, 0), (5, 0), (4, 0)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
        ("Bicep Curl",          [(12, 8), (12, 8), (10, 8)]),
    ]),
    (d(33), [  # Apr 9 — Lower
        ("Squat",               [(8, 72.5), (8, 72.5), (6, 72.5)]),
        ("Romanian Deadlift",   [(10, 55), (10, 55), (8, 55)]),
        ("Leg Press",           [(12, 105), (12, 105), (10, 105)]),
    ]),
    (d(31), [  # Apr 11 — Upper
        ("Bench Press",         [(8, 52.5), (7, 52.5), (6, 52.5)]),
        ("Pull-up",             [(5, 0), (5, 0), (4, 0)]),
    ]),

    # Week 8
    (d(42), [  # Mar 31 — Upper
        ("Bench Press",         [(8, 50), (8, 50), (6, 50)]),
        ("Pull-up",             [(5, 0), (4, 0), (4, 0)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(40), [  # Apr 2 — Lower
        ("Squat",               [(8, 70), (8, 70), (6, 70)]),
        ("Leg Press",           [(12, 100), (12, 100), (10, 100)]),
    ]),
    (d(38), [  # Apr 4 — Upper
        ("Bench Press",         [(8, 50), (7, 50), (6, 50)]),
        ("Pull-up",             [(5, 0), (5, 0), (4, 0)]),
        ("Bicep Curl",          [(12, 8), (12, 8), (10, 8)]),
        ("Tricep Pushdown",     [(12, 15), (12, 15), (10, 15)]),
    ]),

    # Week 7
    (d(49), [  # Mar 24 — Upper
        ("Bench Press",         [(8, 47.5), (8, 47.5), (6, 47.5)]),
        ("Pull-up",             [(4, 0), (4, 0), (3, 0)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),
    (d(47), [  # Mar 26 — Lower
        ("Squat",               [(8, 67.5), (8, 67.5), (6, 67.5)]),
        ("Romanian Deadlift",   [(10, 52.5), (10, 52.5), (8, 52.5)]),
        ("Leg Press",           [(12, 95), (12, 95), (10, 95)]),
    ]),

    # Week 6
    (d(56), [  # Mar 17 — Upper
        ("Bench Press",         [(10, 45), (8, 45), (6, 45)]),
        ("Pull-up",             [(4, 0), (4, 0), (3, 0)]),
        ("Bicep Curl",          [(12, 8), (12, 8), (10, 8)]),
    ]),
    (d(54), [  # Mar 19 — Lower
        ("Squat",               [(8, 65), (8, 65), (6, 65)]),
        ("Leg Press",           [(12, 90), (12, 90), (10, 90)]),
    ]),
    (d(52), [  # Mar 21 — Upper
        ("Bench Press",         [(10, 45), (8, 45), (6, 45)]),
        ("Pull-up",             [(4, 0), (4, 0), (3, 0)]),
        ("Lateral Raise",       [(15, 6), (15, 6), (12, 6)]),
    ]),

    # Week 5
    (d(63), [  # Mar 10 — Upper
        ("Bench Press",         [(10, 42.5), (8, 42.5), (6, 42.5)]),
        ("Pull-up",             [(4, 0), (3, 0), (3, 0)]),
    ]),
    (d(61), [  # Mar 12 — Lower
        ("Squat",               [(8, 62.5), (8, 62.5), (6, 62.5)]),
        ("Romanian Deadlift",   [(10, 50), (10, 50), (8, 50)]),
        ("Leg Press",           [(12, 85), (12, 85), (10, 85)]),
    ]),

    # Week 4
    (d(70), [  # Mar 3 — Upper
        ("Bench Press",         [(10, 40), (8, 40), (6, 40)]),
        ("Pull-up",             [(3, 0), (3, 0), (3, 0)]),
        ("Bicep Curl",          [(12, 8), (12, 8), (10, 8)]),
    ]),
    (d(68), [  # Mar 5 — Lower
        ("Squat",               [(8, 60), (8, 60), (6, 60)]),
        ("Leg Press",           [(12, 80), (12, 80), (10, 80)]),
    ]),
]


# ── Core helpers ─────────────────────────────────────────────────────────────

async def ensure_user(session: AsyncSession, user_id: uuid.UUID, name: str) -> None:
    await session.execute(
        text(
            "INSERT INTO users (id, name) VALUES (:id, :name) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "name": name},
    )


async def seed_user_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    raw_sessions: list[tuple[date, list[tuple[str, list[tuple[int, float]]]]]],
) -> tuple[int, int]:
    sessions_inserted = 0
    exercises_inserted = 0

    for session_date, exercises in raw_sessions:
        # Check for existing session — pass date object, not string
        existing = await session.execute(
            text(
                "SELECT id FROM workout_sessions "
                "WHERE user_id = :uid AND date = :d AND deleted_at IS NULL"
            ),
            {"uid": user_id, "d": session_date},
        )
        row = existing.fetchone()
        if row:
            session_id = row[0]
        else:
            session_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO workout_sessions (id, user_id, date) "
                    "VALUES (:id, :uid, :d)"
                ),
                {"id": session_id, "uid": user_id, "d": session_date},
            )
            sessions_inserted += 1

        for order_idx, (exercise_name, sets) in enumerate(exercises):
            muscle_group = classify_muscle_group(exercise_name)
            exercise_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO workout_exercises "
                    "(id, session_id, name, muscle_group, order_index) "
                    "VALUES (:id, :sid, :name, :mg, :oi)"
                ),
                {
                    "id": exercise_id,
                    "sid": session_id,
                    "name": exercise_name,
                    "mg": muscle_group,
                    "oi": order_idx,
                },
            )
            exercises_inserted += 1

            for set_num, (reps, weight_raw) in enumerate(sets, start=1):
                weight_kg = normalize_weight(weight_raw, "kg")
                await session.execute(
                    text(
                        "INSERT INTO workout_sets "
                        "(id, exercise_id, set_number, reps, weight_kg) "
                        "VALUES (:id, :eid, :sn, :r, :w)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "eid": exercise_id,
                        "sn": set_num,
                        "r": reps,
                        "w": float(weight_kg),
                    },
                )

    return sessions_inserted, exercises_inserted


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        async with session.begin():
            await ensure_user(session, ALEX_ID, "Alex")
            await ensure_user(session, BINH_ID, "Binh")

            alex_s, alex_e = await seed_user_sessions(session, ALEX_ID, ALEX_SESSIONS)
            binh_s, binh_e = await seed_user_sessions(session, BINH_ID, BINH_SESSIONS)

    await engine.dispose()

    print(f"[Alex]  {alex_s} sessions, {alex_e} exercises inserted")
    print(f"[Binh]  {binh_s} sessions, {binh_e} exercises inserted")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
