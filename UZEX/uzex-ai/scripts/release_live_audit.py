"""Actual Gemini through HTTP ASGI chat; stores aggregate QA metrics, never payloads."""

import asyncio
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.api.application import create_app
from app.core.config import Settings
from app.core.logging import configure_logging

# Static QA questions only. Every case routes beyond exact-ID/deterministic language gates.
CASES = [
    ("uz_latn", "2025 yilda nechta bitim bor?", "count"),
    ("uz_latn", "2025 dan oldin nechta bitim?", "before"),
    ("uz_latn", "2025 dan keyin nechta bitim?", "after"),
    ("uz_latn", "2025 yilda tonnada eng kop sement olgan firma", "buyer"),
    ("uz_latn", "2025 yilda tonnada eng kop sement sotgan firma", "seller"),
    ("uz_cyrl", "2025 йилда нечта битим бор?", "count"),
    ("uz_cyrl", "2025 дан олдин нечта битим?", "before"),
    ("uz_cyrl", "2025 дан кейин нечта битим?", "after"),
    ("uz_cyrl", "2025 да тоннада энг кўп цемент олган фирма", "buyer"),
    ("uz_cyrl", "2025 да тоннада энг кўп цемент сотган фирма", "seller"),
    ("ru", "Сколько сделок в 2025 году?", "count"),
    ("ru", "Сколько сделок до 2025 года?", "before"),
    ("ru", "Сколько сделок после 2025 года?", "after"),
    ("ru", "Какая компания купила больше всего цемента в тоннах в 2025 году?", "buyer"),
    ("ru", "Какая компания продала больше всего цемента в тоннах в 2025 году?", "seller"),
    ("uz_latn", "2025 yilda eng kop sement olgan firma", "ambiguous"),
    ("uz_cyrl", "2025 да цементни энг кўп олган фирма", "ambiguous"),
    ("ru", "Какая компания купила больше всего цемента в 2025 году?", "ambiguous"),
    ("uz_latn", "2025 yildagi bitimlar summasi qancha?", "ambiguous"),
    ("ru", "Статус контракта активный", "unsupported"),
]


def fingerprint(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def stats(values):
    if not values:
        return None
    values = sorted(values)
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[math.ceil(0.95 * len(values)) - 1], 3),
    }


async def main():
    load_dotenv(".env", override=False)
    settings = Settings()
    configure_logging()
    app = create_app(settings)
    db = settings.database_path
    before = fingerprint(db)
    rows = []
    model_times = []
    http_times = []
    attempt_times = []
    async with app.router.lifespan_context(app):
        service = app.state.chat_service
        router = service.router
        planner = router.planner
        if planner is None:
            raise RuntimeError("Gemini is not configured")
        await planner.startup()
        original = planner.generate
        trace = {}

        async def measured(*args, **kwargs):
            trace["entered"] = True
            raw, calls, latency = await original(*args, **kwargs)
            trace.update(completed=True, calls=calls, latency=latency)
            return raw, calls, latency

        planner.generate = measured
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://release-audit", timeout=50
        ) as client:
            for index, (language, question, tag) in enumerate(CASES):
                if index:
                    await asyncio.sleep(4)
                await service.cache.clear()
                trace.clear()
                start = time.perf_counter()
                response = await client.post("/api/v1/chat", json={"message": question})
                elapsed = (time.perf_counter() - start) * 1000
                body = response.json()
                expected_language = "ru" if language == "ru" else "uz"
                expected_script = "latin" if language == "uz_latn" else "cyrillic"
                language_ok = (
                    body.get("language") == expected_language
                    and body.get("script") == expected_script
                )
                factual_ok = False
                if tag in ("ambiguous", "unsupported"):
                    factual_ok = body.get("status") == (
                        "AMBIGUOUS" if tag == "ambiguous" else "UNSUPPORTED"
                    )
                elif body.get("status") == "VERIFIED":
                    with router.engine.warehouse.connection() as c:
                        if tag in ("count", "before", "after"):
                            sql = {
                                "count": "SELECT count(*) FROM deals WHERE deal_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'",
                                "before": "SELECT count(*) FROM deals WHERE deal_date<DATE '2025-01-01'",
                                "after": "SELECT count(*) FROM deals WHERE deal_date>=DATE '2026-01-01'",
                            }[tag]
                            value = c.execute(sql).fetchone()[0]
                            ev = body.get("evidence") or {}
                            factual_ok = (
                                str(value) in body.get("answer", "")
                                and ev.get("source_count") == value
                                and bool(ev.get("filters"))
                            )
                        else:
                            # Independent raw-table oracle: explicit buyer/seller identity and physical unit.
                            field = "buyer_inn" if tag == "buyer" else "seller_inn"
                            sql = (
                                f"SELECT d.{field},sum(d.quantity::HUGEINT*d.lot_size) FROM deals d "  # noqa: S608
                                "JOIN contracts c USING(contract_id) WHERE c.tn_ved_code='252329' "
                                "AND d.unit='тонна' AND d.deal_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' "
                                f"GROUP BY d.{field} ORDER BY 2 DESC,1 ASC LIMIT 1"
                            )
                            identity, volume = c.execute(sql).fetchone()
                            ev = body.get("evidence") or {}
                            factual_ok = (
                                identity in body.get("answer", "")
                                and str(volume) in body.get("answer", "")
                                and ev.get("dataset_version") == router.engine.source.version
                            )
                completed = trace.get("completed", False)
                if completed:
                    model_times.append(trace["latency"])
                    http_times.append(elapsed)
                attempt_times.append(elapsed)
                rows.append(
                    {
                        "case_index": index,
                        "language": language,
                        "tag": tag,
                        "http_status": response.status_code,
                        "status": body.get("status"),
                        "gemini_entered": trace.get("entered", False),
                        "gemini_completed": completed,
                        "language_correct": language_ok,
                        "oracle_correct": factual_ok,
                        "passed": completed and language_ok and factual_ok,
                    }
                )
                print(
                    json.dumps(
                        {
                            "processed": index + 1,
                            "completed_inferences": sum(r["gemini_completed"] for r in rows),
                            "passed": sum(r["passed"] for r in rows),
                        }
                    ),
                    flush=True,
                )
        await planner.aclose()
    report = {
        "mode": "REAL_GEMINI_POST_CHAT_ASGI",
        "model": settings.gemini_model,
        "cases": rows,
        "requested": 20,
        "completed_inferences": sum(r["gemini_completed"] for r in rows),
        "passed": sum(r["passed"] for r in rows),
        "gemini_latency_completed": stats(model_times),
        "http_latency_completed": stats(http_times),
        "http_latency_all_attempts": stats(attempt_times),
        "database_sha_unchanged": before == fingerprint(db),
        "external_public_http": False,
        "note": "No mocked/cached/deterministic requests count as completed Gemini. ASGI HTTP is local, not external Render latency.",
    }
    Path("docs/release_live_api_results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}))


if __name__ == "__main__":
    asyncio.run(main())
