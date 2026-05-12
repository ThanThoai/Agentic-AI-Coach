# Feature 4 — Evaluation Pipeline Design

---

## File Layout

```
backend/
├── tests/
│   └── eval/
│       ├── __init__.py
│       ├── dataset/
│       │   ├── rag_testset.json          5 RAG cases
│       │   ├── workout_testset.json      5 workout analysis cases
│       │   ├── agent_testset.json        3 agent cases
│       │   └── adversarial_testset.json  2 adversarial cases
│       ├── metrics/
│       │   ├── __init__.py
│       │   ├── faithfulness.py           M1: LLM-as-judge (Sonnet)
│       │   ├── helpfulness.py            M2: LLM-as-judge (Haiku)
│       │   └── rule_based.py             M3 + M4 + M5: pure Python checks
│       ├── runners/
│       │   ├── __init__.py
│       │   ├── rag_runner.py             calls RAG pipeline directly
│       │   ├── workout_runner.py         calls workout analysis pipeline
│       │   └── agent_runner.py           calls agent service
│       ├── runner.py                     CLI entry-point
│       └── report.py                     JSON + Markdown report renderer
│
└── eval_results/                         gitignored
    ├── results_YYYY-MM-DD_HHMMSS.json
    └── report_YYYY-MM-DD_HHMMSS.md
```

---

## Data Flow

```
JSON test cases
      │
      ▼
runner.py
      ├── rag_runner.py ──────────────► RAGService.query() (direct call)
      │                                 returns: RAGResponse (answer, sources, trace)
      │
      ├── workout_runner.py ──────────► WorkoutService.analyse() (direct call)
      │                                 returns: WorkoutAnalysisResponse (answer, data_summary)
      │
      └── agent_runner.py ────────────► AgentService.run() (direct call)
                                        returns: AgentResponse (answer, tool_calls, usage)
            │
            ▼
      metrics/
      ├── faithfulness.py  ────────────► Sonnet: score_faithfulness()
      ├── helpfulness.py   ────────────► Haiku: score_helpfulness()
      └── rule_based.py    ────────────► pure Python checks (no LLM)
            │
            ▼
      List[CaseResult]
            │
            ▼
      report.py
      ├── eval_results/results_YYYY.json    (machine-readable)
      └── eval_results/report_YYYY.md       (human-readable)
```

---

## Runner Schemas

### Test case input (all categories share this base)

```python
@dataclass
class TestCase:
    id: str
    category: str          # "rag" | "workout" | "agent" | "adversarial"
    question: str
    expected_answer: str   # reference for LLM judge + semantic sim
    pass_criteria: dict    # category-specific rule-based checks
    # RAG-specific
    query_type_expected: str | None = None
    # Workout-specific
    athlete: str | None = None
    question_type_expected: str | None = None
    # Agent-specific
    expected_tools: list[str] | None = None
    # Adversarial-specific
    guardrail_layer_expected: str | None = None
    should_block: bool = False
```

### Case result output

```python
@dataclass
class CaseResult:
    case_id: str
    category: str
    question: str

    # Raw pipeline response
    actual_answer: str
    actual_metadata: dict           # varies per pipeline

    # Metric scores
    faithfulness: float | None      # 0.0–1.0, None if not applicable
    helpfulness: float | None       # 0.0–1.0
    citation_present: bool | None   # M3
    data_values_referenced: bool | None   # M4
    guardrail_effective: bool | None      # M5

    # Derived
    overall_pass: bool
    failure_reasons: list[str]      # which metrics failed and why

    # Performance
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
```

---

## Runner Implementation Sketches

### rag_runner.py

```python
async def run_rag_case(
    case: TestCase,
    providers: PipelineProviders,
    qdrant: QdrantVectorDB,
    db_session: AsyncSession,
) -> tuple[RAGResponse, int]:
    """Returns (response, latency_ms)."""
    t0 = time.monotonic()

    # Guard L1 check (inline, no full pipeline needed for adv-01)
    blocked, reason = hard_block_check(case.question)
    if blocked:
        # Build a synthetic RAGResponse that looks like a blocked response
        ...

    response = await rag_pipeline(
        question=case.question,
        providers=providers,
        qdrant=qdrant,
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    return response, latency_ms
```

### workout_runner.py

```python
async def run_workout_case(
    case: TestCase,
    session: AsyncSession,
    providers: WorkoutPipelineProviders,
) -> tuple[WorkoutAnalysisResponse, int]:
    repo = WorkoutRepository(session)
    service = WorkoutService(repo, providers)

    # Look up user_id from athlete key in test case
    athlete = find_athlete(case.athlete)
    request = WorkoutAnalysisRequest(question=case.question)

    t0 = time.monotonic()
    response = await service.analyse(athlete.user_id, request)
    latency_ms = int((time.monotonic() - t0) * 1000)

    return response, latency_ms
```

### agent_runner.py

```python
async def run_agent_case(
    case: TestCase,
    cfg: Settings,
) -> tuple[AgentResponse, int]:
    # Use coach user_id (any valid coach UUID)
    service = AgentService(cfg)

    t0 = time.monotonic()
    result = await service.run(case.question)
    latency_ms = int((time.monotonic() - t0) * 1000)

    return AgentResponse(**result), latency_ms
```

---

## Metric Runner

```python
async def score_case(
    case: TestCase,
    response: RAGResponse | WorkoutAnalysisResponse | AgentResponse,
    judge_provider: BaseLLMProvider,
    faithfulness_model: str,
    helpfulness_model: str,
) -> CaseResult:
    answer = response.answer
    failure_reasons = []

    # M1 — Faithfulness (RAG + Agent-RAG only)
    faithfulness = None
    if case.category in ("rag", "agent") and hasattr(response, "sources"):
        sources = [s.excerpt for s in response.sources] if response.sources else []
        if sources:
            faithfulness = await score_faithfulness(
                case.question, answer, sources, judge_provider, faithfulness_model
            )
            if faithfulness < 0.7:
                failure_reasons.append(f"faithfulness={faithfulness:.2f} < 0.7")

    # M2 — Helpfulness (all non-adversarial)
    helpfulness = None
    if case.category != "adversarial":
        ctx = "coach" if case.category == "agent" else "athlete"
        helpfulness = await score_helpfulness(
            case.question, answer, ctx, judge_provider, helpfulness_model
        )
        if helpfulness < 0.7:
            failure_reasons.append(f"helpfulness={helpfulness:.2f} < 0.7")

    # M3 — Citation presence (RAG only)
    citation_present = None
    if case.category == "rag" and case.pass_criteria.get("in_scope", True):
        citation_present = check_citation_presence(answer)
        if not citation_present:
            failure_reasons.append("no citation [n] marker in answer")

    # M4 — Data values referenced (workout + agent-analyze)
    data_values_referenced = None
    if case.category == "workout" or (
        case.category == "agent" and "analyze_history" in (case.expected_tools or [])
    ):
        data_values_referenced = check_data_values_referenced(answer, {})
        if not data_values_referenced:
            failure_reasons.append("no numeric data values in answer")

    # M5 — Guardrail effectiveness (adversarial only)
    guardrail_effective = None
    if case.category == "adversarial":
        guardrail_effective = check_guardrail_effectiveness(
            response,
            case.guardrail_layer_expected,
            case.pass_criteria.get("intent_label"),
        )
        if not guardrail_effective:
            failure_reasons.append("guardrail did not block/refuse as expected")

    overall_pass = len(failure_reasons) == 0

    return CaseResult(
        case_id=case.id,
        category=case.category,
        question=case.question,
        actual_answer=answer,
        actual_metadata=_extract_metadata(response),
        faithfulness=faithfulness,
        helpfulness=helpfulness,
        citation_present=citation_present,
        data_values_referenced=data_values_referenced,
        guardrail_effective=guardrail_effective,
        overall_pass=overall_pass,
        failure_reasons=failure_reasons,
        latency_ms=response_latency,
        prompt_tokens=getattr(response.usage, "prompt_tokens", None),
        completion_tokens=getattr(response.usage, "completion_tokens", None),
    )
```

---

## CLI Entry Point

```python
# tests/eval/runner.py

import asyncio
import argparse

async def main():
    parser = argparse.ArgumentParser(description="Coach Agent evaluation harness")
    parser.add_argument("--category", choices=["rag", "workout", "agent", "adversarial", "all"],
                        default="all")
    parser.add_argument("--output-dir", default="eval_results")
    parser.add_argument("--faithfulness-model", default=None)  # uses settings default
    parser.add_argument("--helpfulness-model", default=None)
    args = parser.parse_args()

    # Load test cases
    cases = load_testset(args.category)

    # Run all cases
    results = await run_all(cases, args)

    # Write results
    write_json(results, args.output_dir)
    write_report(results, args.output_dir)

    # Print summary to stdout
    print_summary(results)

if __name__ == "__main__":
    asyncio.run(main())
```

### Usage

```bash
# Full evaluation run
cd backend
uv run python -m tests.eval.runner

# Single category
uv run python -m tests.eval.runner --category rag

# Custom output
uv run python -m tests.eval.runner --output-dir /tmp/eval_results

# Cheaper models for judge (CI preview)
uv run python -m tests.eval.runner \
    --helpfulness-model claude-haiku-4-5-20251001 \
    --faithfulness-model claude-haiku-4-5-20251001
```

---

## Report Format

### JSON result file

```json
{
  "run_id": "2026-05-12T09:00:00Z",
  "pipeline_version": "git-sha",
  "summary": {
    "total_cases": 15,
    "passed": 12,
    "failed": 3,
    "pass_rate": 0.80,
    "avg_faithfulness": 0.85,
    "avg_helpfulness": 0.78,
    "citation_pass_rate": 0.80,
    "data_values_pass_rate": 1.00,
    "guardrail_pass_rate": 1.00
  },
  "by_category": {
    "rag": { "cases": 5, "passed": 4, "avg_faithfulness": 0.88 },
    "workout": { "cases": 5, "passed": 4 },
    "agent": { "cases": 3, "passed": 3 },
    "adversarial": { "cases": 2, "passed": 1 }
  },
  "cases": [
    {
      "id": "rag-01",
      "category": "rag",
      "question": "What is RPE in strength training?",
      "actual_answer": "...",
      "faithfulness": 0.92,
      "helpfulness": 0.84,
      "citation_present": true,
      "data_values_referenced": null,
      "guardrail_effective": null,
      "overall_pass": true,
      "failure_reasons": [],
      "latency_ms": 2340,
      "prompt_tokens": 1450,
      "completion_tokens": 210
    }
  ]
}
```

### Markdown report sections

```markdown
# Coach Agent Evaluation Report — 2026-05-12

## Summary
12/15 cases passed (80.0%)

| Category    | Cases | Passed | Pass Rate |
|-------------|-------|--------|-----------|
| RAG         | 5     | 4      | 80%       |
| Workout     | 5     | 4      | 80%       |
| Agent       | 3     | 3      | 100%      |
| Adversarial | 2     | 1      | 50%       |

## Metric Breakdown
...

## Per-Case Results
...

## Failures
...

## Honest Analysis
What failed, what surprised us, what we would change
```

---

## Cost Estimate

| Component | Model | Cases | ~Tokens/case | Total |
|-----------|-------|-------|-------------|-------|
| RAG answers | Sonnet | 10 | 2 000 | 20 000 |
| Workout answers | Sonnet | 8 | 1 500 | 12 000 |
| Agent answers | Sonnet | 5 | 4 000 | 20 000 |
| Adversarial (L2 classifier) | Haiku | 3 | 500 | 1 500 |
| M1 faithfulness judge | Sonnet | 15 | 1 500 | 22 500 |
| M2 helpfulness judge | Haiku | 23 | 800 | 18 400 |
| **Total** | | | | **~94 000** |

At Anthropic list pricing (~$3/M Sonnet input, $0.25/M Haiku input):
- Sonnet share (~74 500 tokens): ~$0.22
- Haiku share (~19 900 tokens): ~$0.005
- **Full evaluation run ≈ $0.22–$0.30**

Safe to run on every feature branch.
