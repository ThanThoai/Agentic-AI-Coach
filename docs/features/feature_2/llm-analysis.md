# LLM Analysis

**Component of:** Feature 2 — Workout History Analysis
**Last updated:** 2026-05-12

---

## Responsibility

Two LLM steps are used in the analysis endpoint:

| Step | Model | Purpose |
|------|-------|---------|
| **Question classifier** (optional) | Haiku | Identify question type to focus context on the right analytics slice |
| **Answer generator** | Sonnet | Produce a data-backed markdown answer from structured context |

The analytics engine ([analytics.md](./analytics.md)) runs **before** any LLM call and
produces the `AnalysisSummary`. The LLM's job is to interpret the summary and answer
the user's specific question — not to calculate numbers.

---

## Step 1 — Question classifier (Haiku)

### Why classify?

The analytics context (`build_llm_context`) is comprehensive, but the user's question
targets a specific slice:

| Question | Relevant analytics slice |
|----------|------------------------|
| "What's my bench press trend?" | ExerciseStats for Bench Press only |
| "Am I overtraining chest?" | MuscleGroupStats — chest frequency + push/pull ratio |
| "Which muscles am I neglecting?" | `neglected_muscles` list + last_trained dates |
| "Suggest a plan for next week" | All slices — frequency gaps + trend directions |

By classifying first, the context builder can **order and emphasise** the most relevant
section at the top. This reduces prompt size for targeted questions and keeps the LLM
focused on what matters.

### Question types

```python
QuestionType = Literal[
    "TREND",      # "how is my X progressing?" — needs week-over-week data
    "BALANCE",    # "am I overtraining X vs Y?" — needs push/pull or muscle ratios
    "NEGLECT",    # "what am I missing?" — needs neglected_muscles list
    "PLAN",       # "what should I do next week?" — needs full picture
    "GENERAL",    # catch-all — use full context
]
```

### Classifier prompt

```
You are a query classifier for a workout coaching assistant.
Classify the user's question into exactly one of five types:

  TREND    — The user asks about progress, improvement, or trend for a specific
             exercise or body metric over time.
             Examples: "Is my bench press improving?", "Am I getting stronger?"

  BALANCE  — The user asks about imbalance, overtraining, or the ratio between
             two muscle groups or movement patterns.
             Examples: "Am I overtraining chest?", "Is my push/pull balanced?"

  NEGLECT  — The user asks which exercises or muscle groups they are skipping
             or not training enough.
             Examples: "What am I neglecting?", "Which muscles need more work?"

  PLAN     — The user asks for a recommendation or plan based on their history.
             Examples: "What should I train next week?", "How should I adjust my program?"

  GENERAL  — Any other question about workout history.
             Examples: "How many sessions did I do last month?", "What's my total volume?"

Return JSON only — no text outside the JSON:
{"type": "<TYPE>", "focus": "<exercise or muscle group if relevant, else null>"}

Question: {question}
```

### Classifier output

```python
class QuestionClassification(BaseModel):
    type: QuestionType
    focus: str | None   # "Bench Press", "chest", "legs", etc. — for context ordering
```

### When to skip the classifier

The classifier adds ~150 ms. Skip it when:
- `date_from` / `date_to` results in < 2 sessions (insufficient data — answer immediately)
- The question is very short (< 15 chars) — treated as `GENERAL`

---

## Step 2 — Answer generator (Sonnet)

### Prompt design

The system prompt is fixed and cached. The workout context and question are injected
into the user message to avoid breaking the system-prompt cache.

```python
# backend/app/prompts/workout.py

WORKOUT_ANALYSIS_SYSTEM = """\
You are a data-driven fitness coach. A user will share their workout history
(as a structured summary) and ask a question about it.

Rules:
1. Base every claim on the numbers in the provided context. Reference specific figures:
   exercise names, dates, volumes (kg), percentages, session counts.
2. Be concise and actionable. Lead with the direct answer, then support with data.
3. Acknowledge data limitations explicitly:
   - If fewer than 2 sessions exist, say "I don't have enough history to identify trends."
   - If an exercise is missing from the data, say so — do not guess.
   - If a muscle group shows "insufficient data", flag it.
4. Format your answer in clear markdown: use **bold** for key numbers,
   bullet points for lists, and short paragraphs.
5. Do not invent workouts, weights, or dates that are not in the context.
6. If asked for a plan, base it on the frequency and exercise patterns in the data.
   Flag muscle groups that appear neglected and suggest addressing them."""
```

### User message structure

```python
def build_user_message(context: str, question: str) -> str:
    return f"""\
=== USER QUESTION ===
{question}

{context}

Answer the question using only the data shown above.\
"""
```

The context (`build_llm_context` output) is placed in the **user message**, not the
system prompt. This ensures:
- The system prompt (constant) is cached on Anthropic — saves ~70% of its tokens
- The context (variable) changes every request and is not cached

### LLM call

```python
async def generate_analysis(
    question: str,
    context: str,
    provider: BaseLLMProvider,
    model: str | None = None,
) -> LLMResponse:
    return await provider.complete(
        messages=[LLMMessage(role="user", content=build_user_message(context, question))],
        system=WORKOUT_ANALYSIS_SYSTEM,
        max_tokens=600,
        temperature=0.3,   # low temperature for data fidelity; some for readable prose
        model=model,
    )
```

**Why Sonnet and not Haiku?**
Workout analysis answers often require:
- Synthesising data across multiple exercises and muscle groups
- Arithmetic reasoning (ratios, trend percentages)
- Planning (next-week suggestions based on gap analysis)

Haiku handles classification well but produces lower-quality reasoning for multi-step
synthesis. Sonnet's quality difference is measurable here, unlike in the simple
binary classifier case.

---

## Prompt examples

### Example 1 — TREND question (User A)

**User question:** "What's my bench press trend over the last 3 months?"

**Context injected (excerpt):**
```
Bench Press (chest)
  Sessions: 12  |  Avg volume/session: 2 520 kg  |  Max weight: 100 kg
  Trend (week-over-week): +8.5 %  ↑ Progressive
  Last trained: 2026-03-19

--- DELOAD WEEKS ---
2026-W05 (Jan 27–29): total volume ~5 900 kg  (-26 % vs 4-week avg)
  → Bench Press: 60 kg (-20 % vs normal 75 kg)
```

**Expected answer:**
```markdown
Your Bench Press has shown **strong progressive overload** over the 3-month period.

- You trained it **12 times** — roughly once per week on your push days.
- Average session volume is **2 520 kg** with a **+8.5% week-over-week trend** — consistently improving.
- Your peak recorded weight is **100 kg**.

**Deload note:** Week 5 (Jan 27–29) shows intentional reduced load — Bench Press dropped to **60 kg** from your typical **75–80 kg**. This is expected recovery, not a regression.

**Recommendation:** The trend is excellent. Continue adding **2.5 kg** to your top sets every 1–2 sessions to sustain the momentum.
```

---

### Example 2 — BALANCE question (User B)

**User question:** "Am I overtraining chest compared to back?"

**Context injected (excerpt):**
```
chest:  10 sessions  |  total 22 500 kg  |  2.5 sessions/week
back:    4 sessions  |  total  5 600 kg  |  1.0 sessions/week

Bench Press (chest)
  Sessions: 10  |  Max weight: 60 kg (normalised from 130 lb)

Push / Pull ratio: 2.2  (push-dominant)
Chest / Back ratio: 4.0
```

**Expected answer:**
```markdown
Yes — your data reveals a **severe chest-to-back imbalance**.

- **Chest volume:** 22 500 kg over **10 sessions** (2.5×/week)
- **Back volume:** 5 600 kg over **4 sessions** (1.0×/week)
- **Chest / Back ratio: 4.0** — you are doing 4× more chest volume than back. Ideal is close to **1:1**.
- **Push / Pull ratio: 2.2** — significantly push-dominant.

**Risk:** This pattern commonly leads to rounded shoulders, tight pecs, and elevated injury risk (shoulder impingement, rotator cuff strain) over time.

**Recommendation:**
- Match every chest session with a dedicated back session (rows, Face Pulls, lat pulldowns, Pull-Ups).
- Target a chest/back ratio below **1.3** within the next training cycle.
```

---

### Example 3 — NEGLECT question (User B)

**User question:** "Which muscle groups am I neglecting?"

**Context injected (excerpt):**
```
--- NEGLECTED MUSCLES (> 14 days) ---
core (last trained: never in this period)
legs (last trained: 2026-02-14 — 30 days ago)
```

**Expected answer:**
```markdown
Based on the analysed period, **two muscle groups** have been neglected:

- **Core** — not trained at all in the analysed period.
- **Legs** — last trained **30 days ago** (2026-02-14), well past the 14-day threshold. Only **2 squat sessions** appear in your entire 3-month history.

**Recommendation:**
- Add **2 × leg sessions** per week: Squat, Romanian Deadlift, or Leg Press.
- Add **2 × core sessions** per week: planks, hanging leg raises, or ab wheel rollouts.
- Leg training also supports hormonal response (testosterone, GH) that benefits all other lifts.
```

---

### Example 4 — Insufficient data

**User question:** "What's my deadlift trend?"

**Context injected:**
```
⚠ Data note: Only 1 session analysed. Trend confidence: insufficient.

Deadlift (back)
  Sessions: 1  |  Max weight: 140 kg
  Trend: insufficient data (< 2 sessions)
  Last trained: 2026-03-14
```

**Expected answer:**
```markdown
I don't have enough Deadlift history to identify a trend — only **1 session** appears in the selected time window.

To track progression, log at least **2–3 Deadlift sessions** and re-run the analysis.

What I can tell you: your current max recorded weight is **140 kg**.
```

---

## Output validation

After generation, two lightweight checks run before returning the response:

### Length guard

```python
MAX_ANSWER_LENGTH = 2000  # characters

if len(answer) > MAX_ANSWER_LENGTH:
    answer = answer[:MAX_ANSWER_LENGTH] + "… [truncated]"
```

### Hallucination signal detection

Scan for numbers not present in the context (a lightweight check, not a guarantee):

```python
def contains_invented_numbers(answer: str, context: str) -> bool:
    """Flag answers that reference numbers not found in the context.

    Heuristic: extract all integers/decimals from the answer and context;
    any answer number not present in the context is a hallucination signal.
    """
    import re
    answer_nums  = set(re.findall(r"\d+(?:\.\d+)?", answer))
    context_nums = set(re.findall(r"\d+(?:\.\d+)?", context))
    invented = answer_nums - context_nums
    return len(invented) > 0
```

If `contains_invented_numbers` returns `True`, log a warning. Do not reject the
response — the check has false positives (e.g., the LLM computing a derived value
like "14% increase" from two raw numbers). Use the log to calibrate prompt quality.

---

## Model selection guide

| Scenario | Model | Reason |
|----------|-------|--------|
| Question classifier | Haiku | Binary-ish classification; low cost; fast |
| Answer generator — trend / balance / neglect | Sonnet | Multi-step reasoning over numerical data |
| Answer generator — plan generation | Sonnet | Requires synthesising gaps + recommendations |
| High-volume production (cost-sensitive) | Haiku (generator) | Lower quality on synthesis; acceptable for simple GENERAL queries |

Default: **Sonnet for generation**, configurable via `RAG_GENERATION_MODEL` env variable.

---

## Full call flow

```python
# backend/app/services/workout.py

async def analyse_workout(
    question: str,
    history: list[WorkoutSession],    # already fetched by repo, scoped to user
    providers: PipelineProviders,
    date_from: date,
    date_to: date,
) -> WorkoutAnalysisResponse:

    # 1. Handle empty history immediately — no LLM call
    if not history:
        return WorkoutAnalysisResponse(
            answer="I don't have any workout data for the selected period. "
                   "Log some sessions first, then re-run the analysis.",
            data_summary=DataSummary(sessions_analysed=0, insufficient_data=True, ...),
            model=None,
            usage=None,
        )

    # 2. Analytics (pure Python — no LLM)
    summary = compute_analytics(history)

    # 3. Optional question classifier (Haiku) — skip if clearly insufficient data
    question_type = "GENERAL"
    focus = None
    if not summary.insufficient_data:
        classification = await classify_question(
            question, providers.classifier, model=providers.classifier_model
        )
        question_type = classification.type
        focus = classification.focus

    # 4. Build structured context text (ordered by question_type and focus)
    context = build_llm_context(summary, question_type=question_type, focus=focus)
    # build_llm_context signature: (summary, question_type="GENERAL", focus=None) → str
    # see analytics.md for full output format including DELOAD WEEKS section

    # 5. Generate answer (Sonnet)
    llm_response = await generate_analysis(
        question, context,
        providers.generation, model=providers.generation_model,
    )

    # 6. Output validation
    answer = llm_response.content
    if len(answer) > MAX_ANSWER_LENGTH:
        answer = answer[:MAX_ANSWER_LENGTH] + "… [truncated]"

    return WorkoutAnalysisResponse(
        answer=answer,
        data_summary=DataSummary(
            sessions_analysed=summary.sessions_analysed,
            date_range={"from": str(date_from), "to": str(date_to)},
            exercises_found=len(summary.exercises),
            muscle_groups_found=list(summary.muscle_groups.keys()),
            insufficient_data=summary.insufficient_data,
        ),
        model=llm_response.model,
        usage=llm_response.usage,
    )

# Note: DataSummary.deload_weeks_detected = len(summary.deload_weeks)
# e.g. User A's 3-month history produces deload_weeks_detected=1 (ISO week 2026-W05)
```
