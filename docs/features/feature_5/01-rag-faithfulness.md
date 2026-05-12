# Improvement 1 — RAG Faithfulness

## Problem

**9 / 10 RAG cases fail faithfulness.** Average jury score: 0.617 (threshold: 0.700).

The generation model consistently adds detail that is not present in the retrieved chunks. The model "completes" the answer using parametric knowledge when the retrieved context is partial — which it almost always is for well-known fitness topics (RPE, progressive overload, training splits).

**Key evidence — rag-01 (RPE):**
- Knowledge base confirmed: RPE is a 1–10 exertion scale.
- Model added: attribution to Mike Tuchscherer and Borg's scale, full score breakdown (9.5, 9, 8.5…), deload RPE recommendations of 5–6.
- All three jury judges gave 2/5 with confidence 1.00 (zero disagreement).
- Helpfulness jury: all three judges gave 5/5 — the answer is objectively excellent from training knowledge.

**Why rag-06 passed (0.92 faithfulness):** The 1RM calculation question had retrieved chunks that already contained the Epley and Brzycki formulas with worked examples. The model's knowledge matched the source exactly — no hallucination gap existed.

**Core issue:** The generation prompt says "cite retrieved content" but does not say "do not use knowledge you were not given." For a capable LLM these are different instructions.

---

## Changes

### Change 1A — Generation Prompt Hardening (immediate)

**File:** `app/prompts/rag_generation.py` (or wherever the RAG generation system prompt is defined)

Add an explicit suppression clause immediately after the SOURCE EXCERPTS block:

```
CRITICAL CONSTRAINT — SOURCES ONLY:
Your answer must be grounded exclusively in the SOURCE EXCERPTS above.
- Every factual claim must be supported by a specific source chunk and cited with [n].
- If the sources do not contain information needed to answer part of the question,
  write exactly: "The available sources do not cover [topic]." Do not fill the gap
  from general knowledge, even if you are confident the information is correct.
- It is better to give a shorter, fully-cited answer than a longer answer that adds
  uncited detail.
```

**Expected effect:** Reduces hallucination by making the constraint unambiguous. Estimated faithfulness improvement: +0.10–0.15 normalized (based on how judges described the failure: "adds detail beyond sources").

**Risk:** May slightly reduce helpfulness scores on cases where the retrieved context is genuinely thin. Acceptable trade-off given the current 0.617 faithfulness score.

---

### Change 1B — Reduce `max_tokens` for Generation (immediate)

**File:** `app/api/v1/rag.py` or generation config

Reduce `max_tokens` from 512 to **350** for the final answer generation step.

**Rationale:** Longer answers have more surface area for hallucination. For RAG answers covering a specific question with 2–4 retrieved chunks, 350 tokens is sufficient for a well-cited response. If the answer genuinely requires more, the model will use the context efficiently rather than padding with parametric detail.

**Test:** Re-run rag-01 through rag-09 with both changes. Faithfulness should rise; helpfulness should hold or drop only marginally (< 0.05).

---

### Change 1C — Post-Generation Grounding Check (medium term)

After generating the answer, run a lightweight second LLM call that classifies each factual sentence in the answer as:
- `SUPPORTED` — directly traceable to a source chunk
- `INFERRED` — reasonable inference from sources (acceptable)
- `UNSUPPORTED` — no supporting chunk (hallucination)

**Trigger:** If `unsupported_fraction > 0.15` (more than 15% of sentences are unsupported), regenerate the answer with a stricter prompt that explicitly lists the unsupported claims to remove.

**Implementation sketch:**

```python
# app/rag/grounding_check.py

GROUNDING_PROMPT = """
You are a faithfulness auditor. Given an answer and the source excerpts used to generate it,
classify each sentence in the answer as SUPPORTED, INFERRED, or UNSUPPORTED.

SOURCE EXCERPTS:
{context}

ANSWER:
{answer}

Return JSON: {"sentences": [{"text": "...", "label": "SUPPORTED|INFERRED|UNSUPPORTED", "source_idx": n|null}]}
"""

async def check_grounding(answer: str, context: str, llm: BaseLLMProvider) -> GroundingResult:
    ...

async def regenerate_if_needed(answer: str, context: str, llm: BaseLLMProvider) -> str:
    result = await check_grounding(answer, context, llm)
    if result.unsupported_fraction > 0.15:
        return await generate_with_strict_prompt(context, result.unsupported_sentences, llm)
    return answer
```

**Cost:** One extra LLM call per RAG request (lightweight model — use haiku/gpt-4o-mini). Adds ~100–200 ms latency.

**Fallback:** If the grounding check itself fails (LLM error, timeout), return the original answer and log a warning. Never block a response.

---

## Acceptance Criteria

Re-run the full 10-case RAG eval after each change. Target:

| Change | Faithfulness target | Helpfulness floor |
|--------|--------------------|--------------------|
| 1A alone | ≥ 0.720 | ≥ 0.850 |
| 1A + 1B | ≥ 0.740 | ≥ 0.830 |
| 1A + 1B + 1C | ≥ 0.800 | ≥ 0.820 |

RAG category pass rate target after all changes: **≥ 7 / 10 cases**.

---

## Files to Change

| File | Change |
|------|--------|
| `app/prompts/rag_generation.py` | Add suppression clause to system prompt |
| `app/api/v1/rag.py` | Reduce `max_tokens` to 350 |
| `app/rag/grounding_check.py` | New file — grounding auditor (Change 1C) |
| `app/rag/retriever.py` | Wire `check_grounding()` into the generate path |
| `tests/mock/test_rag.py` | Add unit tests for grounding check |
