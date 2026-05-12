# Feature 5 — AI Pipeline Quality Improvements

## Background

Evaluation run `2026-05-12T131014Z` (pipeline version `ef86997`) against 29 cases produced an overall pass rate of **51.7%** (15/29). The dominant failure mode is RAG faithfulness: the generation model supplements partial retrieved context with parametric knowledge, causing 9/10 RAG cases to fail the faithfulness threshold despite high helpfulness scores.

Full findings: [`docs/features/feature_4/EVALUATION.md`](../feature_4/EVALUATION.md)

---

## Improvement Areas

| # | Document | Status | Impact |
|---|----------|--------|--------|
| 1 | [RAG Faithfulness](./01-rag-faithfulness.md) | 🔴 Critical | +40–50 pp pass rate |
| 2 | [Guardrail Hardening](./02-guardrail-hardening.md) | 🔴 Safety | fixes adv-02 miss |
| 3 | [Agent Improvements](./03-agent-improvements.md) | 🟡 Moderate | fixes agent-01, agent-03 |
| 4 | [Data Handling](./04-data-handling.md) | 🟡 Moderate | fixes wo-08, rag-10 |

---

## Prioritization

```
┌──────────────────────────────────────────────────────────┐
│           HIGH IMPACT                                    │
│                                                          │
│  [1] RAG Faithfulness ────────── Fix first. Blocks 9/10 │
│      Prompt hardening (days)                             │
│      + Grounding re-ranker (weeks)                       │
│                                                          │
│  [2] Medical Guardrail ────────── Safety boundary. Fix   │
│      L1 keyword expansion (hours)                        │
│      + L2 trigger lowering (days)                        │
├──────────────────────────────────────────────────────────┤
│           MEDIUM IMPACT                                  │
│                                                          │
│  [3] Agent: date injection ─────── Fix agent-03          │
│      Agent: timeout split ──────── Fix agent-01          │
│                                                          │
│  [4] Data density threshold ────── Fix wo-08             │
│      Out-of-scope message ──────── Fix rag-10            │
└──────────────────────────────────────────────────────────┘
```

## Baseline Metrics (to beat)

| Metric | Baseline | Target |
|--------|----------|--------|
| Overall pass rate | 51.7% | ≥ 75% |
| M1 Faithfulness (avg) | 0.617 | ≥ 0.750 |
| M2 Helpfulness (avg) | 0.868 | ≥ 0.868 (maintain) |
| M5 Guardrail pass rate | 71.4% | 100% |
| RAG category pass rate | 10% | ≥ 70% |
| Agent category pass rate | 60% | ≥ 80% |
