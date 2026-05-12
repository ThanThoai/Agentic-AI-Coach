"""
Athlete roster for the coach agent.
Maps display names / keys to stable UUIDs — must stay in sync with seed_demo.py
and auth.py DEMO_USERS.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Athlete:
    user_id: uuid.UUID
    name: str      # Display name used in responses  ("Alex")
    key: str       # Short key used as alias          ("alex")


ATHLETE_ROSTER: list[Athlete] = [
    Athlete(
        user_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        name="Alex",
        key="alex",
    ),
    Athlete(
        user_id=uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        name="Binh",
        key="binh",
    ),
]

# ── Lookup helpers ─────────────────────────────────────────────────────────────

_BY_LOWER: dict[str, Athlete] = {
    token: a
    for a in ATHLETE_ROSTER
    for token in (a.name.lower(), a.key.lower())
}

# Vietnamese / common "all athletes" expressions
_ALL_TOKENS: frozenset[str] = frozenset({
    "all", "everyone", "everybody", "all athletes",
    "tất cả", "cả hai", "mọi người", "hết", "toàn bộ",
})


def find_athlete(name: str) -> Athlete | None:
    """Return the Athlete matching *name* (case-insensitive), or None."""
    return _BY_LOWER.get(name.strip().lower())


def resolve_athletes(text: str) -> list[Athlete]:
    """
    Scan *text* for athlete references and return the matched athletes.

    Rules:
    - If the text contains an "all athletes" expression → return all athletes.
    - Otherwise scan word-by-word for name / key matches.
    - If nothing is found → return all athletes (safe default for a coach
      question that doesn't name anyone specifically).
    """
    lower = text.lower()

    # "All athletes" shortcut
    for tok in _ALL_TOKENS:
        if tok in lower:
            return list(ATHLETE_ROSTER)

    # Individual name matches
    found: list[Athlete] = []
    seen: set[str] = set()
    for word in re.split(r"[\s,;/]+", lower):
        word = word.strip("'\"()[]")
        if not word:
            continue
        a = _BY_LOWER.get(word)
        if a and a.key not in seen:
            found.append(a)
            seen.add(a.key)

    return found if found else list(ATHLETE_ROSTER)


def roster_summary() -> str:
    """One-line description of the roster for injection into the system prompt."""
    return ", ".join(f"{a.name} (key: {a.key})" for a in ATHLETE_ROSTER)
