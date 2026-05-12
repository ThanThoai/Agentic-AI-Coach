"""Render evaluation results to JSON and Markdown."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .schemas import CaseResult


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


class _Summary:
    def __init__(
        self,
        total_cases: int,
        passed: int,
        failed: int,
        pass_rate: float,
        avg_faithfulness: float | None,
        avg_helpfulness: float | None,
        citation_pass_rate: float | None,
        data_values_pass_rate: float | None,
        guardrail_pass_rate: float | None,
    ) -> None:
        self.total_cases = total_cases
        self.passed = passed
        self.failed = failed
        self.pass_rate = pass_rate
        self.avg_faithfulness = avg_faithfulness
        self.avg_helpfulness = avg_helpfulness
        self.citation_pass_rate = citation_pass_rate
        self.data_values_pass_rate = data_values_pass_rate
        self.guardrail_pass_rate = guardrail_pass_rate

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class _CatStats:
    def __init__(self, cases: int, passed: int, pass_rate: float, avg_faithfulness: float | None) -> None:
        self.cases = cases
        self.passed = passed
        self.pass_rate = pass_rate
        self.avg_faithfulness = avg_faithfulness

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def _summary_stats(results: list[CaseResult]) -> _Summary:
    total = len(results)
    passed = sum(1 for r in results if r.overall_pass)
    faith_scores = [r.faithfulness_score for r in results if r.faithfulness_score is not None]
    help_scores = [r.helpfulness_score for r in results if r.helpfulness_score is not None]
    citation_results = [r.citation_present for r in results if r.citation_present is not None]
    data_results = [r.data_values_referenced for r in results if r.data_values_referenced is not None]
    guard_results = [r.guardrail_effective for r in results if r.guardrail_effective is not None]

    return _Summary(
        total_cases=total,
        passed=passed,
        failed=total - passed,
        pass_rate=round(passed / total, 3) if total else 0.0,
        avg_faithfulness=_avg(faith_scores),
        avg_helpfulness=_avg(help_scores),
        citation_pass_rate=_avg([float(x) for x in citation_results]),
        data_values_pass_rate=_avg([float(x) for x in data_results]),
        guardrail_pass_rate=_avg([float(x) for x in guard_results]),
    )


def _by_category(results: list[CaseResult]) -> dict[str, _CatStats]:
    cats: dict[str, list[CaseResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)

    out: dict[str, _CatStats] = {}
    for cat, rs in cats.items():
        total = len(rs)
        passed = sum(1 for r in rs if r.overall_pass)
        faith = [r.faithfulness_score for r in rs if r.faithfulness_score is not None]
        out[cat] = _CatStats(
            cases=total,
            passed=passed,
            pass_rate=round(passed / total, 2) if total else 0.0,
            avg_faithfulness=round(sum(faith) / len(faith), 3) if faith else None,
        )
    return out


def write_json(results: list[CaseResult], output_dir: Path) -> Path:
    ts = _timestamp()
    summary = _summary_stats(results)
    by_cat = _by_category(results)
    data = {
        "run_id": ts,
        "pipeline_version": _git_sha(),
        "summary": summary.to_dict(),
        "by_category": {cat: s.to_dict() for cat, s in by_cat.items()},
        "cases": [
            {
                "id": r.case_id,
                "category": r.category,
                "question": r.question,
                "actual_answer": r.actual_answer[:500] + "..." if len(r.actual_answer) > 500 else r.actual_answer,
                "faithfulness": r.faithfulness_score,
                "faithfulness_disputed": r.faithfulness_disputed,
                "faithfulness_verdict": r.faithfulness_verdict,
                "helpfulness": r.helpfulness_score,
                "helpfulness_disputed": r.helpfulness_disputed,
                "helpfulness_verdict": r.helpfulness_verdict,
                "citation_present": r.citation_present,
                "data_values_referenced": r.data_values_referenced,
                "guardrail_effective": r.guardrail_effective,
                "overall_pass": r.overall_pass,
                "failure_reasons": r.failure_reasons,
                "latency_ms": r.latency_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
            }
            for r in results
        ],
    }
    path = output_dir / f"results_{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def write_report(results: list[CaseResult], output_dir: Path) -> Path:
    ts = _timestamp()
    summary = _summary_stats(results)
    by_cat = _by_category(results)

    lines: list[str] = []
    lines.append(f"# Coach Agent Evaluation Report — {ts[:10]}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"{summary.passed}/{summary.total_cases} cases passed ({summary.pass_rate*100:.1f}%)")
    lines.append("")
    lines.append("| Category | Cases | Passed | Pass Rate |")
    lines.append("|----------|-------|--------|-----------|")
    for cat, s in by_cat.items():
        lines.append(f"| {cat.capitalize()} | {s.cases} | {s.passed} | {s.pass_rate*100:.0f}% |")
    lines.append("")

    lines.append("## Metric Breakdown")
    lines.append("")
    lines.append("| Metric | Score |")
    lines.append("|--------|-------|")
    if summary.avg_faithfulness is not None:
        lines.append(f"| M1 Avg Faithfulness | {summary.avg_faithfulness:.3f} |")
    if summary.avg_helpfulness is not None:
        lines.append(f"| M2 Avg Helpfulness | {summary.avg_helpfulness:.3f} |")
    if summary.citation_pass_rate is not None:
        lines.append(f"| M3 Citation Pass Rate | {summary.citation_pass_rate*100:.0f}% |")
    if summary.data_values_pass_rate is not None:
        lines.append(f"| M4 Data Values Pass Rate | {summary.data_values_pass_rate*100:.0f}% |")
    if summary.guardrail_pass_rate is not None:
        lines.append(f"| M5 Guardrail Pass Rate | {summary.guardrail_pass_rate*100:.0f}% |")
    lines.append("")

    lines.append("## Per-Case Results")
    lines.append("")
    lines.append("| ID | Category | Pass | Faithfulness | Helpfulness | Failure Reasons |")
    lines.append("|----|----------|------|-------------|-------------|-----------------|")
    for r in results:
        faith_str = f"{r.faithfulness_score:.2f}" if r.faithfulness_score is not None else "—"
        if r.faithfulness_disputed:
            faith_str += " ⚠️"
        help_str = f"{r.helpfulness_score:.2f}" if r.helpfulness_score is not None else "—"
        if r.helpfulness_disputed:
            help_str += " ⚠️"
        pass_str = "✅" if r.overall_pass else "❌"
        reasons = "; ".join(r.failure_reasons[:2]) or "—"
        lines.append(f"| {r.case_id} | {r.category} | {pass_str} | {faith_str} | {help_str} | {reasons} |")
    lines.append("")

    lines.append("## Detailed Results")
    lines.append("")
    for r in results:
        pass_str = "✅ PASS" if r.overall_pass else "❌ FAIL"
        lines.append(f"### {r.case_id} — {pass_str}")
        lines.append(f"**Question:** {r.question}")
        lines.append("")

        answer_text = r.actual_answer
        if len(answer_text) > 600:
            answer_text = answer_text[:600] + "…"
        lines.append(f"**Answer:**\n```\n{answer_text}\n```")
        lines.append("")

        if r.failure_reasons:
            lines.append("**Failure reasons:**")
            for reason in r.failure_reasons:
                lines.append(f"- {reason}")
            lines.append("")

        if r.faithfulness_verdict:
            v = r.faithfulness_verdict
            disputed_tag = "  ⚠️ disputed" if v["disputed"] else ""
            lines.append(
                f"**M1 Faithfulness** — mean={v['mean']:.2f}  "
                f"normalized={v['normalized']:.2f}  "
                f"std={v['std_dev']:.2f}  "
                f"confidence={v['confidence']:.2f}{disputed_tag}"
            )
            for judge, score in v["scores"].items():
                reason = v["reasons"].get(judge, "")
                lines.append(f"- **{judge}** {score}/5 — {reason}")
            lines.append("")

        if r.helpfulness_verdict:
            v = r.helpfulness_verdict
            disputed_tag = "  ⚠️ disputed" if v["disputed"] else ""
            lines.append(
                f"**M2 Helpfulness** — mean={v['mean']:.2f}  "
                f"normalized={v['normalized']:.2f}  "
                f"std={v['std_dev']:.2f}  "
                f"confidence={v['confidence']:.2f}{disputed_tag}"
            )
            for judge, score in v["scores"].items():
                reason = v["reasons"].get(judge, "")
                lines.append(f"- **{judge}** {score}/5 — {reason}")
            lines.append("")

        if not r.faithfulness_verdict and not r.helpfulness_verdict and not r.failure_reasons:
            lines.append("_No LLM verdicts for this case (rule-based only)._")
            lines.append("")

    lines.append("## Honest Analysis")
    lines.append("")
    lines.append("_Fill in after reviewing the run: what failed, what surprised you, what you would change._")
    lines.append("")

    path = output_dir / f"report_{ts}.md"
    path.write_text("\n".join(lines))
    return path


def print_summary(results: list[CaseResult]) -> None:
    summary = _summary_stats(results)
    print(f"{'='*50}")
    print("EVALUATION SUMMARY")
    print(f"{'='*50}")
    print(f"Total:  {summary.total_cases}")
    print(f"Passed: {summary.passed}  ({summary.pass_rate*100:.1f}%)")
    print(f"Failed: {summary.failed}")

    by_cat = _by_category(results)
    print()
    print(f"{'Category':<14} {'Cases':>6} {'Passed':>8} {'Rate':>8}")
    print("-" * 40)
    for cat, s in by_cat.items():
        print(f"{cat.capitalize():<14} {s.cases:>6} {s.passed:>8} {s.pass_rate*100:>7.0f}%")

    if summary.avg_faithfulness is not None:
        print(f"\nM1 Faithfulness:  {summary.avg_faithfulness:.3f}")
    if summary.avg_helpfulness is not None:
        print(f"M2 Helpfulness:   {summary.avg_helpfulness:.3f}")
    print(f"{'='*50}")
