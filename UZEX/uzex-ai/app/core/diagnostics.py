"""Allowlisted technical diagnostics; never accepts a question, prompt or result."""

import logging
import time
from uuid import uuid4


def correlation_id() -> str:
    return uuid4().hex


def diagnostic(stage, exception_class, error_category, started, request_id):
    logging.getLogger("uzex.diagnostics").info(
        "stage",
        extra={
            "diagnostic": {
                "stage": stage,
                "exception_class": exception_class,
                "error_category": error_category,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "request_id": request_id,
            }
        },
    )
