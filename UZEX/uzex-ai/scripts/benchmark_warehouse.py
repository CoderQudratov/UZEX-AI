"""Measure fixed warehouse integrity reads, not AI or end-user request latency."""

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from app.core.config import Settings
from app.db.runtime import ReadOnlyWarehouse

OPERATIONS = {
    "row_count": ("SELECT count(*) FROM deals", []),
    "primary_key_lookup": ("SELECT amount,contract_id FROM deals WHERE deal_id=?", [100001]),
    "currency_reconciliation": (
        "SELECT currency,sum(amount),sum(amount_uzs) FROM deals_enriched GROUP BY currency",
        [],
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/uzex.duckdb"))
    parser.add_argument("--output", type=Path, default=Path("docs/warehouse_performance.json"))
    args = parser.parse_args()
    warehouse = ReadOnlyWarehouse(Settings(database_path=args.database))
    results = {}
    for name, (sql, parameters) in OPERATIONS.items():
        elapsed = []
        for index in range(33):
            start = time.perf_counter()
            with warehouse.connection() as connection:
                connection.execute(sql, parameters).fetchall()
            duration = (time.perf_counter() - start) * 1000
            if index >= 3:
                elapsed.append(duration)
        elapsed.sort()
        results[name] = {
            "samples": len(elapsed),
            "p50_ms": round(statistics.median(elapsed), 3),
            "p95_ms": round(elapsed[math.ceil(0.95 * len(elapsed)) - 1], 3),
            "min_ms": round(min(elapsed), 3),
            "max_ms": round(max(elapsed), 3),
        }
    report = {
        "benchmark": "Phase 2 fixed warehouse integrity reads",
        "environment": "Local Python 3.12; 128MB DuckDB memory cap, 1 thread, no spill",
        "method": (
            "3 warm-ups + 30 sequential samples per operation, "
            "fresh read-only connection per sample"
        ),
        "p95_method": "nearest rank; p50 is median",
        "results": results,
        "limitations": (
            "OS filesystem cache warm; includes lease/open/close. "
            "Not Render, concurrency, API or Gemini latency."
        ),
        "extra_indexes_added": 0,
        "materialized_summaries_added": 0,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
