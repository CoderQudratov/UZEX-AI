"""Fixed events and allowlisted technical diagnostics; no payload or exception text."""

import json
import logging
import logging.config
import math
import re

EVENTS = frozenset({"startup", "shutdown", "startup_failed", "internal_error"})


class EventOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return isinstance(record.msg, str) and record.msg in EVENTS and not record.args


class EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Deliberately excludes exception text, arguments, context and arbitrary extras.
        return json.dumps({"level": record.levelname, "event": record.msg})


class DiagnosticFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        data = getattr(record, "diagnostic", None)
        if record.msg != "stage" or record.args or not isinstance(data, dict):
            return False
        if set(data) != {"stage", "exception_class", "error_category", "elapsed_ms", "request_id"}:
            return False
        if data["stage"] not in {
            "language_detector",
            "prompt_builder",
            "gemini_client",
            "groq_client",
            "json_validation",
            "semantic_guard",
            "query_execution",
            "answer_formatter",
        }:
            return False
        if not isinstance(data["request_id"], str) or not re.fullmatch(
            "[a-f0-9]{32}", data["request_id"]
        ):
            return False
        for key in ("exception_class", "error_category"):
            value = data[key]
            if value is None and key == "exception_class":
                continue
            if not isinstance(value, str) or not re.fullmatch("[A-Za-z_][A-Za-z_0-9]{0,63}", value):
                return False
        elapsed = data["elapsed_ms"]
        return isinstance(elapsed, (int, float)) and math.isfinite(elapsed) and elapsed >= 0


class DiagnosticFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # No level, message, arbitrary extra, exception text, traceback or parameters.
        return json.dumps(
            {
                key: record.diagnostic[key]
                for key in (
                    "stage",
                    "exception_class",
                    "error_category",
                    "elapsed_ms",
                    "request_id",
                )
            }
        )


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "filters": {"events": {"()": EventOnlyFilter}, "diagnostics": {"()": DiagnosticFilter}},
            "formatters": {
                "events": {"()": EventFormatter},
                "diagnostics": {"()": DiagnosticFormatter},
            },
            "handlers": {
                "null": {"class": "logging.NullHandler"},
                "events": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "events",
                    "filters": ["events"],
                },
                "diagnostics": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "diagnostics",
                    "filters": ["diagnostics"],
                },
            },
            "root": {"handlers": ["null"], "level": "CRITICAL"},
            "loggers": {
                "uzex.events": {"handlers": ["events"], "level": "INFO", "propagate": False},
                "uzex.diagnostics": {
                    "handlers": ["diagnostics"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
        }
    )
