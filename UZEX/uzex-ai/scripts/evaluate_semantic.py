"""Real API evaluation against fixed QA fixtures. Persists aggregate metrics only."""

import argparse
import asyncio
import json
import math
import statistics
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from app.agent.answer_formatter import format_answer
from app.agent.gemini_client import GeminiPlanner, PlannerFailure
from app.agent.query_executor import QueryExecutor
from app.agent.query_validator import validate_plan
from app.agent.semantic_models import LANGUAGE_MAP
from app.agent.semantic_router import SemanticRouter
from app.core.config import Settings
from tests.fixtures.multilingual_cases import CASES, expected_plan


def normalized_plan(plan, engine=None):
    plan = validate_plan(plan)
    filters = []
    for f in plan.filters:
        values = f.values
        if f.op == "between" and all(type(v) is date for v in values):
            filters.extend([(f.field, "gte", str(values[0])), (f.field, "lte", str(values[1]))])
        elif f.op == "lt" and type(values[0]) is date:
            filters.append((f.field, "lte", str(values[0] - timedelta(days=1))))
        elif f.op == "gt" and type(values[0]) is date:
            filters.append((f.field, "gte", str(values[0] + timedelta(days=1))))
        else:
            filters.append((f.field, f.op, tuple(str(v) for v in values)))
    pending_entities = []
    kind_for = {
        "seller_inn": "company",
        "buyer_inn": "company",
        "seller_broker_code": "broker",
        "buyer_broker_code": "broker",
        "product_name": "product",
        "tn_ved_code": "tn_ved",
        "region": "region",
        "status": "status",
    }
    for entity in plan.entities:
        resolution = (
            engine.resolver.resolve(kind_for.get(entity.field, ""), entity.text) if engine else None
        )
        if resolution and resolution.status == "VERIFIED":
            filters.append((entity.field, "eq", (resolution.candidates[0].value,)))
        else:
            pending_entities.append((entity.field, entity.text))
    filters = list(set(filters))
    groups = set(plan.group_by)
    for role in ("seller", "buyer"):
        if role + "_inn" in groups:
            groups.discard(role + "_name")
        if role + "_broker_code" in groups:
            groups.discard(role + "_broker_name")
    return {
        "kind": plan.kind,
        "lookup": plan.lookup.model_dump() if plan.lookup else None,
        "metrics": sorted(plan.metrics),
        "group_by": sorted(groups),
        "filters": sorted(filters, key=str),
        "money_mode": plan.money_mode,
        "entities": sorted(pending_entities),
        "order_by": [(o.field, o.direction) for o in plan.order_by],
        "limit": plan.limit if groups or plan.kind == "records" else None,
        "periods": [(str(p.start), str(p.end)) for p in plan.periods],
        "fields": sorted(plan.fields),
    }


def summarize(values):
    if not values:
        return None
    values = sorted(values)
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[math.ceil(0.95 * len(values)) - 1], 3),
    }


async def evaluate(args):
    if args.env_file:
        if args.env_file.is_file():
            load_dotenv(args.env_file, override=False)
    settings = Settings()
    if args.model:
        settings = Settings.model_validate({**settings.model_dump(), "gemini_model": args.model})
    if not settings.gemini_api_key or not settings.gemini_model:
        print(json.dumps({"status": "NOT_CONFIGURED", "real_api_evaluated": False}))
        return 2
    planner = None
    try:
        planner = GeminiPlanner(settings)
        stamp = time.perf_counter()
        await planner.startup()
        startup_ms = (time.perf_counter() - stamp) * 1000
        engine = QueryExecutor(settings)
        router = SemanticRouter(
            engine,
            planner,
            reference_date=date(2026, 11, 5),
            max_concurrency=settings.max_concurrent_queries,
        )
        cases = CASES[args.start : args.start + args.limit] if args.limit else CASES[args.start :]
        correct = model_correct = model_cases = unsupported = unsupported_rejected = 0
        model_times = []
        attempt_times = []
        completed_correct = 0
        false_verified = 0
        processed = 0
        consecutive_provider_errors = 0
        failure_fields = {}
        completed_cases = 0
        end_times = []
        failure_types = {}
        failure_cases = []
        for index, case in enumerate(cases):
            if index and args.spacing_seconds:
                await asyncio.sleep(args.spacing_seconds)
            processed += 1
            start = time.perf_counter()
            before_responses = router.metrics.model_responses
            result = await router.understand(case.text)
            completed = router.metrics.model_responses > before_responses
            expected = expected_plan(case)
            expected_status = "VERIFIED" if expected else case.expected.split(":", 1)[0]
            same = result.status == expected_status and result.language == case.language
            if same and expected:
                same = result.plan is not None and normalized_plan(result.plan) == normalized_plan(
                    expected
                )
            if same and expected is None:
                # Scope/metric ambiguity category must also be correct; technical errors never pass.
                # The fixed oracle requires semantic status; wording/reason variants do not
                # authorize execution. Contrastive negation signatures have separate tests.
                same = result.status == case.expected.split(":", 1)[0]
            semantic_same = same
            if result.status == "VERIFIED" and not semantic_same:
                false_verified += 1
                if expected and result.plan:
                    observed = normalized_plan(result.plan, engine)
                    wanted = normalized_plan(expected, engine)
                    for key in observed:
                        if observed[key] != wanted[key]:
                            failure_fields[key] = failure_fields.get(key, 0) + 1
            if result.plan is not None and result.status == "VERIFIED":
                verified = await asyncio.to_thread(engine.execute, result.plan)
                format_answer(verified, LANGUAGE_MAP[result.language])
                if verified.status == "ERROR":
                    same = False
            correct += int(same)
            if result.model_calls:
                model_cases += 1
                model_correct += int(same)
            if result.model_latency_ms is not None:
                attempt_times.append(result.model_latency_ms)
                if completed:
                    model_times.append(result.model_latency_ms)
            if completed:
                completed_cases += 1
                completed_correct += int(semantic_same)
            end_times.append((time.perf_counter() - start) * 1000)
            if case.language == "unsupported":
                unsupported += 1
                unsupported_rejected += result.status == "UNSUPPORTED" and result.plan is None
            if not same:
                category = result.reason or "PLAN_MISMATCH"
                failure_types[category] = failure_types.get(category, 0) + 1
                # Only static fixture indexes, never the question, plan, response or identifiers.
                failure_cases.append(args.start + index)
            if result.status == "ERROR" and result.reason.startswith("MODEL_"):
                consecutive_provider_errors += 1
            else:
                consecutive_provider_errors = 0
            if processed % 10 == 0:
                print(
                    json.dumps(
                        {
                            "progress_processed": processed,
                            "planned": len(cases),
                            "correct": correct,
                            "completed_model_cases": completed_cases,
                        }
                    ),
                    flush=True,
                )
            if consecutive_provider_errors >= 3:
                break
        report = {
            "mode": "LIVE_GEMINI",
            "model": settings.gemini_model,
            "samples": processed,
            "planned_samples": len(cases),
            "correct_semantic_cases": correct,
            "overall_router_accuracy": correct / processed,
            "model_cases": model_cases,
            "model_correct_cases": model_correct,
            "model_operational_accuracy": model_correct / model_cases if model_cases else None,
            "model_completed_cases": completed_cases,
            "model_semantic_accuracy": completed_correct / completed_cases
            if completed_cases
            else None,
            "unsupported_language_cases": unsupported,
            "unsupported_language_rejected": unsupported_rejected,
            "unsupported_language_rejection_rate": unsupported_rejected / unsupported
            if unsupported
            else None,
            "json_validation_failures": router.metrics.json_validation_failures,
            "guard_rejections": router.metrics.guard_rejections,
            "model_calls": router.metrics.model_calls,
            "model_latency": summarize(model_times),
            "model_attempt_latency": summarize(attempt_times),
            "end_to_end_latency": summarize(end_times),
            "startup_model_metadata_ms": round(startup_ms, 3),
            "failure_categories": failure_types,
            "failure_plan_fields": failure_fields,
            "false_verified_cases": false_verified,
            "provider_status_counts": dict(planner.api_error_counts),
            "fixture_failure_indexes": failure_cases,
            "semantic_quality_gate": (
                "PASS"
                if processed >= 100
                and completed_cases >= 50
                and completed_correct == completed_cases
                and false_verified == 0
                and router.metrics.json_validation_failures == 0
                and unsupported_rejected == unsupported
                else "INCOMPLETE_OR_FAIL"
            ),
            "acceptance": "PASS"
            if correct == len(cases) and len(cases) >= 100
            else "INCOMPLETE_OR_FAIL",
            "privacy": (
                "Aggregate QA metrics only; no utterances, query plans, "
                "parameters or answers stored"
            ),
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": report["acceptance"],
                    "samples": processed,
                    "planned_samples": len(cases),
                    "correct": correct,
                    "model_semantic_accuracy": report["model_semantic_accuracy"],
                }
            )
        )
        return 0 if report["acceptance"] == "PASS" else 1
    except PlannerFailure as exc:
        print(json.dumps({"status": "ERROR", "reason": exc.reason, "real_api_evaluated": False}))
        return 1
    finally:
        if planner is not None:
            await planner.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--spacing-seconds", type=float, default=4)
    parser.add_argument(
        "--model", help="Explicit reviewed candidate; never changes the .env default"
    )
    parser.add_argument("--output", type=Path, default=Path("docs/semantic_live_metrics.json"))
    args = parser.parse_args()
    if args.limit < 0 or args.start < 0 or args.spacing_seconds < 0:
        parser.error("limit must be nonnegative")
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())
