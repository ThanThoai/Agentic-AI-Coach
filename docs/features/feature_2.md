## Feature 2 — Workout History Analysis (Required)

Build an endpoint that accepts a user's workout history (JSON array) and a natural language question, then returns an AI-generated insight.

Example workout entry:
```json
{ 
  "date": "2026-03-20", 
  "exercise": "Bench Press", 
  "sets": [ 
    { "reps": 10, "weight": 80, "unit": "kg" }, 
    { "reps": 8, "weight": 85, "unit": "kg" }, 
    { "reps": 6, "weight": 90, "unit": "kg" } 
  ]
}
```

Example questions the system should handle:
"What's my bench press trend over the last month?"
"Which exercises am I neglecting?"
"Am I overtraining chest compared to back?"
"Suggest a workout plan for next week based on my history"

The system must:
- Parse and analyze workout data before passing to the LLM — do not dump raw JSON into the prompt
- Provide data-backed responses (reference specific numbers, dates, trends)
- Handle edge cases: empty history, insufficient data, unknown exercises
- Maintain user data isolation — User A's history must never appear in User B's context or response. Include at least 1 test case verifying this boundary.
