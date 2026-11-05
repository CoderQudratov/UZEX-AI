"""Fixed Phase 3 regression benchmarks; never consumes or records user questions/plans."""

import argparse
import json
import math
import statistics
import time
from datetime import date
from pathlib import Path

from app.agent.query_executor import QueryExecutor
from app.agent.query_models import Filter, Lookup, Order, QueryPlan
from app.core.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/uzex.duckdb"))
    parser.add_argument("--output", type=Path, default=Path("docs/query_engine_performance.json"))
    args = parser.parse_args()
    start = time.perf_counter()
    engine = QueryExecutor(Settings(database_path=args.database))
    initialization = (time.perf_counter() - start) * 1000
    plans = {
        "exact_lookup": QueryPlan(
            kind="lookup", lookup=Lookup(entity="transaction", identifier=100001)
        ),
        "aggregation": QueryPlan(
            kind="aggregate", metrics=("sum_amount", "count"), money_mode="uzs"
        ),
        "ranking": QueryPlan(
            kind="aggregate",
            metrics=("sum_amount", "count"),
            money_mode="uzs",
            group_by=("seller_inn",),
            order_by=(Order(field="sum_amount"),),
            limit=10,
        ),
        "multi_table_join": QueryPlan(
            kind="records",
            fields=(
                "deal_id",
                "seller_name",
                "buyer_name",
                "seller_broker_name",
                "buyer_broker_name",
                "currency",
                "amount_uzs",
            ),
            filters=(Filter(field="deal_date", op="gte", values=(date(2026, 10, 1),)),),
            limit=20,
        ),
    }
    results = {}
    for name, plan in plans.items():
        durations = []
        for i in range(33):
            stamp = time.perf_counter()
            result = engine.execute(plan)
            elapsed = (time.perf_counter() - stamp) * 1000
            if result.status != "VERIFIED":
                raise RuntimeError("Benchmark correctness prerequisite failed")
            if i >= 3:
                durations.append(elapsed)
        durations.sort()
        results[name] = {
            "samples": 30,
            "p50_ms": round(statistics.median(durations), 3),
            "p95_ms": round(durations[math.ceil(0.95 * len(durations)) - 1], 3),
            "min_ms": round(min(durations), 3),
            "max_ms": round(max(durations), 3),
        }
    report = {
        "benchmark": "Phase 3 deterministic QueryPlan to VerifiedResult",
        "initialization_ms": round(initialization, 3),
        "results": results,
        "method": (
            "3 warm-ups then 30 sequential samples per operation; p50 median; p95 nearest rank"
        ),
        "scope": (
            "Includes validation, artifact stat guard, semantic probes, compilation, "
            "read-only lease, exact arithmetic, sorting and result validation"
        ),
        "limits": (
            "128MB DuckDB engine memory, 1 thread, 5-second lease, no spill, "
            "100 output rows, 20000 groups"
        ),
        "limitations": "Local warm OS cache; single process; not Render, HTTP or Gemini latency",
        "privacy": (
            "Only aggregate timings are recorded. No queries, parameters, plans, "
            "entities or answers are persisted."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
