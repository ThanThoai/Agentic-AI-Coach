# Step: conflict detection LLM re-check
# Runs only on candidate pairs flagged by the heuristic pass.
# Input (user message): two excerpts A and B passed inline.
# Expected output: {"conflict": true | false, "topic": "<short phrase or empty>"}

CONFLICT_CHECK_SYSTEM = """\
Compare two fitness knowledge excerpts.
Determine if they make mutually contradictory factual claims — claims that
cannot both be true for the same population and goal.

Different recommendations for different populations (beginner vs advanced)
or different goals (strength vs hypertrophy) are NOT contradictions.
Only flag hard factual contradictions (e.g. "X increases Y" vs "X decreases Y").

Return JSON only: {"conflict": true | false, "topic": "<one short phrase or empty>"}"""
