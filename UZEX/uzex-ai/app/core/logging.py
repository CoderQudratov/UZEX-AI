"""Only fixed lifecycle/error events may reach stdout. No request-derived fields."""

import json
import logging
import logging.config

EVENTS = frozenset({"startup", "shutdown", "startup_failed", "internal_error"})


class EventOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return isinstance(record.msg, str) and record.msg in EVENTS and not record.args


class EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Deliberately excludes exception text, arguments, context and arbitrary extras.
        return json.dumps({"level": record.levelname, "event": record.msg})


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "filters": {"events": {"()": EventOnlyFilter}},
            "formatters": {"events": {"()": EventFormatter}},
            "handlers": {
                "null": {"class": "logging.NullHandler"},
                "events": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "events",
                    "filters": ["events"],
                },
            },
            "root": {"handlers": ["null"], "level": "CRITICAL"},
            "loggers": {
                "uzex.events": {"handlers": ["events"], "level": "INFO", "propagate": False}
            },
        }
    )
