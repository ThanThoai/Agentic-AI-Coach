# v1.0 — Core Coaching MVP

**Status:** In development
**Target:** First public release

## Features in this version

| Feature | Doc | Status |
|---|---|---|
| Workout tracking | [workout-tracking.md](./workout-tracking.md) | Specced |
| AI coaching chat | [ai-coaching.md](./ai-coaching.md) | Specced |

## Scope

v1.0 establishes the foundation:
- Users can log workouts (exercises, sets, reps, weight)
- AI coach analyses workout history and answers questions
- Knowledge base (20 fitness docs) is used as RAG context
- Multi-provider LLM support (Anthropic default)
- Qdrant vector search for knowledge retrieval

## Out of scope for v1.0

- Nutrition tracking
- Workout plan generation
- Social / sharing features
- Mobile app
