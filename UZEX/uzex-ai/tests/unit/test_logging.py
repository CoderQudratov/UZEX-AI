import json
import logging

from app.core.logging import EventFormatter, EventOnlyFilter


def test_only_fixed_events_are_allowed():
    check = EventOnlyFilter()
    assert check.filter(logging.makeLogRecord({"msg": "startup", "args": ()}))
    for message in ("private-user-question", {"body": "private-user-question"}):
        assert not check.filter(logging.makeLogRecord({"msg": message, "args": ()}))
    assert not check.filter(logging.makeLogRecord({"msg": "startup", "args": ("secret",)}))


def test_formatter_cannot_serialize_payload_or_exception():
    record = logging.makeLogRecord(
        {
            "msg": "internal_error",
            "levelname": "ERROR",
            "args": (),
            "exc_info": (ValueError, ValueError("private-exception"), None),
            "question": "private-user-question",
            "api_key": "private-key",
        }
    )
    assert json.loads(EventFormatter().format(record)) == {
        "level": "ERROR",
        "event": "internal_error",
    }
