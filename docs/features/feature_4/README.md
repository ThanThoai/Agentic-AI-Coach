# Feature 4 — Evaluation Pipeline

**Status:** Design | **Last updated:** 2026-05-12

---

## Requirement

> Build an evaluation system that measures the quality of RAG, analysis, and agent outputs.
>
> - Test set: ≥ 15 question-answer pairs (5 RAG, 5 workout analysis, 3 agent, 2 adversarial)
>
> **Implemented: 28 cases** — 10 RAG, 8 workout, 5 agent, 5 adversarial
> - ≥ 3 evaluation metrics — one LLM-as-judge, one rule-based
> - Run evaluation and include results
> - Honest analysis: what failed, what surprised you, what you would change

---

## Approach Summary

The evaluation system is a **standalone Python evaluation harness** that:

1. Loads curated test cases from JSON fixtures
2. Calls each pipeline directly (no HTTP) to get actual outputs
3. Scores outputs with a metric suite (LLM-as-judge + rule-based + semantic similarity)
4. Writes a structured JSON result file and a human-readable Markdown report

The harness runs with `uv run python -m tests.eval.runner` and requires a live Qdrant + DB instance plus real API keys (marked `live`).

---

## System Architecture

```
tests/eval/
├── dataset/
│   ├── rag_testset.json           5 RAG cases
│   ├── workout_testset.json       5 workout analysis cases
│   ├── agent_testset.json         3 agent (coach assist) cases
│   └── adversarial_testset.json   2 guardrail stress cases
│
├── metrics/
│   ├── faithfulness.py            LLM-as-judge: answer grounded in retrieved context?
│   ├── helpfulness.py             LLM-as-judge: quality, tone, actionability
│   ├── rule_based.py              citation presence, data values, guardrail block
│   └── semantic_sim.py            cosine similarity vs expected answer (via embeddings)
│
├── runners/
│   ├── rag_runner.py              calls RAG pipeline, collects answer + sources + trace
│   ├── workout_runner.py          calls workout analysis pipeline
│   └── agent_runner.py            calls agent loop, collects tool_calls + final answer
│
├── runner.py                      CLI entry-point — orchestrates all runners + metrics
└── report.py                      renders JSON results → Markdown report
```

Outputs land in `backend/eval_results/` (gitignored):

```
eval_results/
├── results_2026-05-12.json        machine-readable full detail
└── report_2026-05-12.md           human-readable summary with per-case breakdown
```

---

## Component docs

| File | Scope |
|------|-------|
| [testset.md](./testset.md) | All 15 test cases: questions, expected answers, pass criteria |
| [metrics.md](./metrics.md) | Metric definitions, prompts, scoring rubrics, implementation |
| [pipeline.md](./pipeline.md) | Runner design, output schema, report format, usage commands |

---

## Design decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Harness vs HTTP | Direct function calls | Avoids network overhead and auth; lets us inspect intermediate pipeline state (trace, sources, tool_calls) |
| Test fixture format | JSON files per pipeline | Human-readable, diff-friendly, easy to extend without touching code |
| LLM-as-judge model | Sonnet for faithfulness, Haiku for helpfulness | Faithfulness requires careful reasoning; helpfulness is faster/cheaper to judge |
| Adversarial scope | Guardrail L1 + L2 only | L3 output filter is deterministic (regex + bounds check); no LLM-judge needed |
| Semantic similarity | text-embedding-3-small cosine | Same model used by RAG pipeline — consistent embedding space |
| Failure threshold | Pass = metric ≥ 0.7 for LLM scores; binary for rule-based | Empirical threshold aligned with production quality bar |

---

## Key constraints

- Test cases must **not** depend on specific dates — workout data is relative (e.g. "last 4 weeks"). The seed script uses relative `date.today() + offset` so tests always have valid data.
- Agent test cases must **fully specify expected tool usage** (`expected_tools: ["analyze_history"]`) so the routing check is deterministic.
- Adversarial cases must check the response text for refusal language AND the pipeline metadata (`in_scope: false` for RAG, guardrail trace fields) — not just the response content alone.
