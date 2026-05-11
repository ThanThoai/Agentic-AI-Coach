from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.rag.parser import ParsedChunk

# ---------------------------------------------------------------------------
# Rule tables keyed on slug extracted from source_file name
# ---------------------------------------------------------------------------

TOPIC_TYPE_RULES: dict[str, str] = {
    "bench-press": "technique",
    "squat": "technique",
    "deadlift": "technique",
    "overhead-press": "technique",
    "barbell-row": "technique",
    "pull-up": "technique",
    "isolation": "technique",
    "progressive-overload": "programming",
    "periodization": "programming",
    "deload": "programming",
    "rpe-rir": "programming",
    "one-rep-max": "programming",
    "workout-split": "programming",
    "training-for-beginners": "programming",
    "muscle-recovery": "safety",
    "common-injuries": "safety",
    "warm-up-cooldown": "safety",
    "nutrition": "nutrition",
}

TAG_RULES: dict[str, list[str]] = {
    "bench-press": ["compound", "push", "upper_body", "chest", "powerlifting"],
    "squat": ["compound", "squat_pattern", "lower_body", "legs", "powerlifting"],
    "deadlift": ["compound", "hinge", "full_body", "back", "legs", "powerlifting"],
    "overhead-press": ["compound", "push", "upper_body", "shoulders"],
    "barbell-row": ["compound", "pull", "upper_body", "back"],
    "pull-up": ["compound", "pull", "upper_body", "back", "arms"],
    "isolation": ["isolation", "hypertrophy"],
    "progressive-overload": ["progressive_overload", "strength", "hypertrophy"],
    "periodization": ["periodization", "programming", "strength"],
    "deload": ["deload", "recovery", "programming"],
    "rpe-rir": ["rpe", "rir", "strength", "programming"],
    "one-rep-max": ["strength", "powerlifting", "programming"],
    "workout-split-ppl": ["ppl_split", "programming", "hypertrophy"],
    "workout-split-upper-lower": ["programming", "strength", "hypertrophy"],
    "workout-split-full-body": ["programming", "full_body", "beginner"],
    "muscle-recovery": ["recovery", "injury_prevention"],
    "common-injuries": ["injury_prevention", "safety"],
    "warm-up-cooldown": ["warm_up", "recovery", "safety"],
    "nutrition-basics": ["nutrition"],
    "training-for-beginners": ["beginner", "programming", "strength"],
}

DIFFICULTY_RULES: dict[str, list[str]] = {
    "training-for-beginners": ["beginner"],
    "workout-split-full-body": ["beginner", "intermediate"],
    "workout-split-ppl": ["intermediate", "advanced"],
    "workout-split-upper-lower": ["intermediate", "advanced"],
    "periodization": ["intermediate", "advanced"],
    "one-rep-max": ["intermediate", "advanced"],
}

DEFAULT_DIFFICULTY = ["beginner", "intermediate", "advanced"]


# ---------------------------------------------------------------------------
# LLM fallback prompt
# ---------------------------------------------------------------------------

METADATA_EXTRACTION_PROMPT = """\
Analyse this fitness document and return JSON only — no markdown fences, no explanation:
{{
  "topic_type": "<technique | programming | safety | nutrition>",
  "difficulty": ["<beginner | intermediate | advanced>", ...],
  "tags": ["<3-6 concise lowercase tags>"]
}}

Document title: {doc_title}
Content excerpt (first 300 chars): {excerpt}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_slug(source_file: str) -> str:
    """Strip directory, extension, and leading digits: '08-bench-press.md' → 'bench-press'."""
    stem = re.sub(r"\.[^.]+$", "", source_file)          # remove extension
    stem = re.sub(r"^[\d\-_]+", "", stem)                 # strip leading numbers
    return stem.lower()


def _match_rule_key(slug: str, rules: dict) -> str | None:
    """Return the first rule key that is a substring of the file slug."""
    for key in rules:
        if key in slug:
            return key
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ChunkMetadata:
    tags: list[str]
    difficulty: list[str]
    topic_type: str


def extract_metadata(chunk: ParsedChunk) -> ChunkMetadata:
    """Rule-based metadata extraction. Returns defaults when no rule matches."""
    slug = _file_slug(chunk.source_file)

    topic_key = _match_rule_key(slug, TOPIC_TYPE_RULES)
    tag_key = _match_rule_key(slug, TAG_RULES)
    diff_key = _match_rule_key(slug, DIFFICULTY_RULES)

    topic_type = TOPIC_TYPE_RULES[topic_key] if topic_key else "technique"
    tags = TAG_RULES[tag_key] if tag_key else []
    difficulty = DIFFICULTY_RULES[diff_key] if diff_key else DEFAULT_DIFFICULTY

    return ChunkMetadata(tags=tags, difficulty=difficulty, topic_type=topic_type)


async def extract_metadata_llm(chunk: ParsedChunk, provider) -> ChunkMetadata:  # type: ignore[type-arg]
    """LLM-assisted fallback for documents not covered by rule tables."""
    from app.llm.base import LLMMessage

    excerpt = chunk.text[:300].replace("\n", " ")
    prompt = METADATA_EXTRACTION_PROMPT.format(
        doc_title=chunk.doc_title,
        excerpt=excerpt,
    )
    response = await provider.complete(
        messages=[LLMMessage(role="user", content=prompt)],
        max_tokens=256,
        temperature=0.0,
    )
    try:
        data = json.loads(response.content.strip())
        return ChunkMetadata(
            tags=data.get("tags", []),
            difficulty=data.get("difficulty", DEFAULT_DIFFICULTY),
            topic_type=data.get("topic_type", "technique"),
        )
    except (json.JSONDecodeError, KeyError):
        return ChunkMetadata(tags=[], difficulty=DEFAULT_DIFFICULTY, topic_type="technique")


def attach_metadata(chunk: ParsedChunk, meta: ChunkMetadata) -> ParsedChunk:
    """Mutate chunk in-place with extracted metadata and return it."""
    chunk.tags = meta.tags
    chunk.difficulty = meta.difficulty
    chunk.topic_type = meta.topic_type
    return chunk
