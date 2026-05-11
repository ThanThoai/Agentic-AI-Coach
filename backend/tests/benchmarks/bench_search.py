"""
Search latency benchmark — dense vs sparse vs hybrid.

Measures Qdrant query latency in isolation (no embedding API calls).
Query vectors are pre-computed once before timing starts.

Usage:
    # Quick run — all modes, 104 seed points, 100 queries each
    uv run python -m tests.benchmarks.bench_search

    # Against a real Qdrant server
    uv run python -m tests.benchmarks.bench_search --url http://localhost:6333

    # Larger corpus, more iterations
    uv run python -m tests.benchmarks.bench_search --n-points 500 --n-queries 200

    # Single mode
    uv run python -m tests.benchmarks.bench_search --mode dense
    uv run python -m tests.benchmarks.bench_search --mode sparse
    uv run python -m tests.benchmarks.bench_search --mode hybrid

    # Also benchmark BM25 vector computation (local CPU)
    uv run python -m tests.benchmarks.bench_search --include-bm25

Options:
    --url           Qdrant URL  (default: :memory:)
    --collection    Collection  (default: bench_kb)
    --n-points      Seed points (default: 104)
    --n-queries     Queries per mode (default: 100)
    --warmup        Warmup iterations, not recorded (default: 10)
    --limit         Top-K per query (default: 5)
    --prefetch      Over-fetch for hybrid RRF (default: 20)
    --vector-size   Dense vector dims (default: 1536)
    --mode          dense | sparse | hybrid | all (default: all)
    --include-bm25  Also benchmark local BM25 sparse vector computation
    --seed          Random seed for reproducibility (default: 42)
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import statistics
import time
from dataclasses import dataclass, field
from itertools import cycle
from typing import Callable, Awaitable

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[-1]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


@dataclass
class BenchResult:
    name: str
    n: int
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p50_ms(self) -> float:
        return _percentile(self.latencies_ms, 50)

    @property
    def p90_ms(self) -> float:
        return _percentile(self.latencies_ms, 90)

    @property
    def p99_ms(self) -> float:
        return _percentile(self.latencies_ms, 99)

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def stddev_ms(self) -> float:
        return statistics.stdev(self.latencies_ms) if len(self.latencies_ms) > 1 else 0.0

    @property
    def rps(self) -> float:
        if not self.mean_ms or self.mean_ms == 0:
            return 0.0
        return 1000.0 / self.mean_ms

    def summary_line(self) -> str:
        return (
            f"  min={self.min_ms:.2f}ms  "
            f"p50={self.p50_ms:.2f}ms  "
            f"p90={self.p90_ms:.2f}ms  "
            f"p99={self.p99_ms:.2f}ms  "
            f"max={self.max_ms:.2f}ms  "
            f"mean={self.mean_ms:.2f}ms  "
            f"σ={self.stddev_ms:.2f}ms  "
            f"RPS={self.rps:.0f}"
        )


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

def _random_dense(size: int, rng: random.Random) -> list[float]:
    """Unit-normalized random dense vector."""
    v = [rng.gauss(0, 1) for _ in range(size)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _random_sparse(vocab: int = 50_000, n_terms: int = 80, rng: random.Random | None = None) -> SparseVector:
    """Random sparse vector mimicking a BM25 output (~80 non-zero terms)."""
    if rng is None:
        rng = random.Random()
    indices = sorted(rng.sample(range(vocab), n_terms))
    values = [abs(rng.gauss(1.5, 0.5)) for _ in range(n_terms)]
    return SparseVector(indices=indices, values=values)


_TOPIC_TYPES = ["technique", "programming", "safety", "nutrition"]
_DIFFICULTIES = [
    ["beginner", "intermediate", "advanced"],
    ["intermediate", "advanced"],
    ["beginner"],
]
_SOURCES = [
    "01-bench-press.md", "02-squat.md", "03-deadlift.md",
    "04-overhead-press.md", "05-barbell-row.md", "06-pull-up.md",
    "07-isolation.md", "08-progressive-overload.md", "09-periodization.md",
    "10-deload.md", "11-rpe-rir.md", "12-one-rep-max.md",
    "13-nutrition-basics.md", "14-workout-split-ppl.md",
    "15-workout-split-full-body.md", "16-muscle-recovery.md",
    "17-common-injuries.md", "18-warm-up-cooldown.md",
    "19-training-for-beginners.md", "20-workout-split-upper-lower.md",
]


def _make_payload(idx: int, _rng: random.Random) -> dict:
    src = _SOURCES[idx % len(_SOURCES)]
    return {
        "source_file": src,
        "doc_title": src.replace(".md", "").replace("-", " ").title(),
        "section_title": f"Section {idx % 6}",
        "chunk_index": str(idx % 6),
        "text": f"Sample chunk text for document {src}, chunk {idx}.",
        "topic_type": _TOPIC_TYPES[idx % len(_TOPIC_TYPES)],
        "difficulty": _DIFFICULTIES[idx % len(_DIFFICULTIES)],
        "tags": ["strength", "compound"][: (idx % 2) + 1],
    }


# ---------------------------------------------------------------------------
# Qdrant setup
# ---------------------------------------------------------------------------

async def _setup_collection(
    client: AsyncQdrantClient,
    collection: str,
    vector_size: int,
    n_points: int,
    seed: int,
) -> tuple[list[list[float]], list[SparseVector]]:
    """Create hybrid collection and seed it. Returns (dense_queries, sparse_queries)."""
    rng = random.Random(seed)

    # Drop if exists
    existing = {c.name for c in (await client.get_collections()).collections}
    if collection in existing:
        await client.delete_collection(collection)

    await client.create_collection(
        collection_name=collection,
        vectors_config={"dense": VectorParams(size=vector_size, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )

    # Generate and upsert points in batches of 50
    dense_bank: list[list[float]] = []
    sparse_bank: list[SparseVector] = []

    batch_size = 50
    for batch_start in range(0, n_points, batch_size):
        batch_end = min(batch_start + batch_size, n_points)
        points = []
        for i in range(batch_start, batch_end):
            d = _random_dense(vector_size, rng)
            s = _random_sparse(rng=rng)
            dense_bank.append(d)
            sparse_bank.append(s)
            points.append(
                PointStruct(
                    id=i,
                    vector={"dense": d, "sparse": s},
                    payload=_make_payload(i, rng),
                )
            )
        await client.upsert(collection_name=collection, points=points, wait=True)

    return dense_bank, sparse_bank


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

async def _run_benchmark(
    name: str,
    fn: Callable[[], Awaitable[None]],
    n_queries: int,
    warmup: int,
) -> BenchResult:
    result = BenchResult(name=name, n=n_queries)

    # Warmup — not recorded
    for _ in range(warmup):
        await fn()

    # Timed iterations
    for _ in range(n_queries):
        t0 = time.perf_counter()
        await fn()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        result.latencies_ms.append(elapsed_ms)

    return result


async def bench_dense(
    client: AsyncQdrantClient,
    collection: str,
    dense_queries: list[list[float]],
    n_queries: int,
    warmup: int,
    limit: int,
) -> BenchResult:
    """Dense vector search via query_points (single named vector)."""
    q_iter = cycle(dense_queries)

    async def _query():
        q = next(q_iter)
        await client.query_points(
            collection_name=collection,
            query=q,
            using="dense",
            limit=limit,
            with_payload=False,
        )

    return await _run_benchmark("dense", _query, n_queries, warmup)


async def bench_sparse(
    client: AsyncQdrantClient,
    collection: str,
    sparse_queries: list[SparseVector],
    n_queries: int,
    warmup: int,
    limit: int,
) -> BenchResult:
    """Sparse (BM25) vector search via query_points."""
    q_iter = cycle(sparse_queries)

    async def _query():
        q = next(q_iter)
        await client.query_points(
            collection_name=collection,
            query=q,
            using="sparse",
            limit=limit,
            with_payload=False,
        )

    return await _run_benchmark("sparse", _query, n_queries, warmup)


async def bench_hybrid(
    client: AsyncQdrantClient,
    collection: str,
    dense_queries: list[list[float]],
    sparse_queries: list[SparseVector],
    n_queries: int,
    warmup: int,
    limit: int,
    prefetch_limit: int,
) -> BenchResult:
    """Hybrid search: dense + sparse prefetch with RRF fusion."""
    d_iter = cycle(dense_queries)
    s_iter = cycle(sparse_queries)

    async def _query():
        d = next(d_iter)
        s = next(s_iter)
        await client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=d, using="dense", limit=prefetch_limit),
                Prefetch(query=s, using="sparse", limit=prefetch_limit),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=False,
        )

    return await _run_benchmark("hybrid (RRF)", _query, n_queries, warmup)


async def bench_hybrid_with_filter(
    client: AsyncQdrantClient,
    collection: str,
    dense_queries: list[list[float]],
    sparse_queries: list[SparseVector],
    n_queries: int,
    warmup: int,
    limit: int,
    prefetch_limit: int,
) -> BenchResult:
    """Hybrid search with payload filter (topic_type == technique)."""
    d_iter = cycle(dense_queries)
    s_iter = cycle(sparse_queries)

    payload_filter = Filter(
        must=[FieldCondition(key="topic_type", match=MatchValue(value="technique"))]
    )

    async def _query():
        d = next(d_iter)
        s = next(s_iter)
        await client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=d, using="dense", limit=prefetch_limit, filter=payload_filter),
                Prefetch(query=s, using="sparse", limit=prefetch_limit, filter=payload_filter),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=False,
        )

    return await _run_benchmark("hybrid + filter", _query, n_queries, warmup)


def bench_bm25_cpu(n_queries: int, warmup: int) -> BenchResult:
    """BM25 sparse vector computation — local CPU, synchronous."""
    try:
        from fastembed import SparseTextEmbedding
    except ImportError:
        print("  [SKIP] fastembed not installed — skipping BM25 CPU benchmark")
        return BenchResult(name="bm25-cpu", n=0)

    print("  Loading Qdrant/bm25 model (may download ~10 MB on first run)...")
    model = SparseTextEmbedding(model_name="Qdrant/bm25")

    sample_texts = [
        "how do I bench press correctly",
        "progressive overload for intermediate lifters",
        "RPE 8 on squat 5x5",
        "what is 1RM and how do I calculate it",
        "Romanian Deadlift muscle groups",
    ]

    result = BenchResult(name="bm25-cpu", n=n_queries)

    # Warmup
    for i in range(warmup):
        next(model.embed([sample_texts[i % len(sample_texts)]]))

    # Timed
    for i in range(n_queries):
        t0 = time.perf_counter()
        next(model.embed([sample_texts[i % len(sample_texts)]]))
        result.latencies_ms.append((time.perf_counter() - t0) * 1000)

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


def _print_result(r: BenchResult) -> None:
    if r.n == 0:
        return
    print(f"  [{r.name}]  n={r.n}")
    print(f"  {r.summary_line()}")


def _print_table(results: list[BenchResult]) -> None:
    valid = [r for r in results if r.n > 0]
    if not valid:
        return

    print(f"\n{'─' * 70}")
    print("  Summary comparison")
    print(f"{'─' * 70}")

    col_w = [20, 8, 8, 8, 8, 8, 8, 8]
    headers = ["Mode", "n", "min", "p50", "p90", "p99", "max", "RPS"]
    header_row = "  " + "".join(h.ljust(w) for h, w in zip(headers, col_w))
    print(header_row)
    print("  " + "-" * sum(col_w))

    for r in valid:
        row = [
            r.name,
            str(r.n),
            f"{r.min_ms:.2f}ms",
            f"{r.p50_ms:.2f}ms",
            f"{r.p90_ms:.2f}ms",
            f"{r.p99_ms:.2f}ms",
            f"{r.max_ms:.2f}ms",
            f"{r.rps:.0f}",
        ]
        print("  " + "".join(v.ljust(w) for v, w in zip(row, col_w)))

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    print(f"\nSearch Latency Benchmark")
    print(f"  url={args.url}  collection={args.collection}")
    print(f"  n_points={args.n_points}  n_queries={args.n_queries}  warmup={args.warmup}")
    print(f"  limit={args.limit}  prefetch={args.prefetch}  vector_size={args.vector_size}")
    print(f"  mode={args.mode}  seed={args.seed}")

    # BM25 CPU benchmark (synchronous, no Qdrant needed)
    bm25_result = BenchResult(name="bm25-cpu", n=0)
    if args.include_bm25:
        _print_header("BM25 sparse vector computation (local CPU)")
        bm25_result = bench_bm25_cpu(args.n_queries, args.warmup)
        _print_result(bm25_result)

    # Connect to Qdrant
    if args.url == ":memory:":
        client = AsyncQdrantClient(":memory:")
    else:
        client = AsyncQdrantClient(url=args.url, api_key=os.getenv("QDRANT_API_KEY") or None)

    _print_header(f"Seeding collection '{args.collection}' with {args.n_points} hybrid points")
    t_seed = time.perf_counter()
    dense_bank, sparse_bank = await _setup_collection(
        client, args.collection, args.vector_size, args.n_points, args.seed
    )
    seed_ms = (time.perf_counter() - t_seed) * 1000
    print(f"  Done in {seed_ms:.0f}ms")

    # Build query vectors (sample from the seeded bank for realistic queries)
    n_q_vectors = min(args.n_queries, len(dense_bank))
    dense_queries = random.Random(args.seed + 1).choices(dense_bank, k=n_q_vectors)
    sparse_queries = random.Random(args.seed + 1).choices(sparse_bank, k=n_q_vectors)

    results: list[BenchResult] = []
    if args.include_bm25 and bm25_result.n > 0:
        results.append(bm25_result)

    run_all = args.mode == "all"

    if run_all or args.mode == "dense":
        _print_header("Dense search")
        r = await bench_dense(
            client, args.collection, dense_queries,
            args.n_queries, args.warmup, args.limit,
        )
        _print_result(r)
        results.append(r)

    if run_all or args.mode == "sparse":
        _print_header("Sparse search (BM25 vectors)")
        r = await bench_sparse(
            client, args.collection, sparse_queries,
            args.n_queries, args.warmup, args.limit,
        )
        _print_result(r)
        results.append(r)

    if run_all or args.mode == "hybrid":
        _print_header("Hybrid search (dense + sparse → RRF fusion)")
        r = await bench_hybrid(
            client, args.collection, dense_queries, sparse_queries,
            args.n_queries, args.warmup, args.limit, args.prefetch,
        )
        _print_result(r)
        results.append(r)

        _print_header("Hybrid + payload filter (topic_type == technique)")
        r = await bench_hybrid_with_filter(
            client, args.collection, dense_queries, sparse_queries,
            args.n_queries, args.warmup, args.limit, args.prefetch,
        )
        _print_result(r)
        results.append(r)

    _print_table(results)

    await client.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Qdrant search latency benchmark: dense vs sparse vs hybrid."
    )
    p.add_argument("--url", default=":memory:", help="Qdrant URL (default: :memory:)")
    p.add_argument("--collection", default="bench_kb", help="Collection name")
    p.add_argument("--n-points", type=int, default=104, help="Seed points (default: 104)")
    p.add_argument("--n-queries", type=int, default=100, help="Queries per mode (default: 100)")
    p.add_argument("--warmup", type=int, default=10, help="Warmup iterations (default: 10)")
    p.add_argument("--limit", type=int, default=5, help="Top-K per query (default: 5)")
    p.add_argument("--prefetch", type=int, default=20, help="Over-fetch for hybrid RRF (default: 20)")
    p.add_argument("--vector-size", type=int, default=1536, help="Dense vector dims (default: 1536)")
    p.add_argument(
        "--mode",
        choices=["dense", "sparse", "hybrid", "all"],
        default="all",
        help="Which search mode(s) to benchmark (default: all)",
    )
    p.add_argument(
        "--include-bm25",
        action="store_true",
        help="Also benchmark local BM25 sparse vector computation",
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args))
