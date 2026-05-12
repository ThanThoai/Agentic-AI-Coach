"""Knowledge-base topic coverage audit (Change 4D).

Run after ingestion to identify which common fitness topics have no matching chunks
above the relevance threshold. Topics with no coverage will produce OUT_OF_SCOPE
responses — this audit surfaces gaps so content can be prioritised.

Usage (as part of ingestion CLI):
    uv run python -m app.rag.ingestion --audit-coverage
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Reference list of common fitness topics that should be covered in the knowledge base.
EXPECTED_TOPICS: list[str] = [
    "RPE rating of perceived exertion",
    "progressive overload",
    "periodization training cycles",
    "one rep max 1RM calculation",
    "deload week",
    "training splits push pull legs",
    "upper lower training split",
    "full body training split",
    "warm up before lifting",
    "muscle recovery time",
    "bench press technique",
    # Topics identified as gaps from evaluation:
    "blood flow restriction training BFR",
    "injury rehabilitation return to training",
    "altitude training performance",
    "electrolyte hydration for athletes",
]

COVERAGE_SCORE_THRESHOLD = 0.35


@dataclass
class CoverageReport:
    total_topics: int
    covered: list[str]
    missing: list[str]

    @property
    def coverage_pct(self) -> float:
        if self.total_topics == 0:
            return 0.0
        return len(self.covered) / self.total_topics * 100

    def __str__(self) -> str:
        lines = [
            f"Knowledge-base coverage: {len(self.covered)}/{self.total_topics} topics "
            f"({self.coverage_pct:.0f}%)",
        ]
        if self.missing:
            lines.append("\nMissing topics (produce OUT_OF_SCOPE responses):")
            for t in self.missing:
                lines.append(f"  - {t}")
        return "\n".join(lines)


async def audit_coverage(
    embedder: Any,
    qdrant: Any,
    *,
    topics: list[str] | None = None,
) -> CoverageReport:
    """Query the vector DB for each topic and report which have no matching chunks."""
    from app.rag.retriever import retrieve

    topics = topics or EXPECTED_TOPICS
    covered: list[str] = []
    missing: list[str] = []

    async def _check(topic: str) -> bool:
        try:
            _, merged = await retrieve(
                [topic],
                "SIMPLE",  # QueryType is a Literal, not an enum
                embedder,
                qdrant,
                max_sources=1,
            )
            return bool(merged)
        except Exception:
            log.warning("coverage_audit.check_failed", topic=topic, exc_info=True)
            return False

    results = await asyncio.gather(*[_check(t) for t in topics])
    for topic, has_coverage in zip(topics, results):
        (covered if has_coverage else missing).append(topic)

    report = CoverageReport(
        total_topics=len(topics),
        covered=covered,
        missing=missing,
    )
    log.info(
        "coverage_audit.complete",
        covered=len(covered),
        missing=len(missing),
        coverage_pct=round(report.coverage_pct, 1),
    )
    return report
