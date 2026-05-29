"""Tests for the structured logging configuration."""

from __future__ import annotations

import json
import logging

import pytest

from app.logging_config import (
    JsonFormatter,
    configure_logging,
    request_id_var,
)


def _record(msg: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="netforge",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_core_fields() -> None:
    out = json.loads(JsonFormatter().format(_record("boot")))
    assert out["level"] == "INFO"
    assert out["logger"] == "netforge"
    assert out["msg"] == "boot"
    assert "ts" in out


def test_json_formatter_includes_request_id_when_set() -> None:
    token = request_id_var.set("rid-123")
    try:
        out = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)
    assert out["request_id"] == "rid-123"


def test_json_formatter_omits_request_id_when_unset() -> None:
    # Default context value is None → key absent (not null noise).
    out = json.loads(JsonFormatter().format(_record()))
    assert "request_id" not in out


def test_json_formatter_promotes_structured_extras() -> None:
    out = json.loads(
        JsonFormatter().format(
            _record("request", event="request", status=200, duration_ms=12)
        )
    )
    assert out["event"] == "request"
    assert out["status"] == 200
    assert out["duration_ms"] == 12


def test_json_formatter_serialises_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("crash")
        record.exc_info = sys.exc_info()
        out = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in out["exc_info"]


def test_configure_logging_is_idempotent_and_switches_format() -> None:
    root = logging.getLogger()
    try:
        configure_logging("info", "json")
        configure_logging("debug", "json")
        # Repeated calls must not stack handlers.
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG

        configure_logging("info", "text")
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        # Restore a sane default so later tests aren't affected.
        configure_logging("info", "text")


@pytest.mark.parametrize("fmt", ["text", "json"])
def test_emit_path_never_keyerrors_without_request_context(fmt: str) -> None:
    """Drive the real emit path (which applies the handler's filter) to prove
    that logging outside any request — scheduler, startup — never raises on a
    missing request_id, in either format."""
    import io

    configure_logging("info", fmt)
    root = logging.getLogger()
    handler = root.handlers[0]
    stream = io.StringIO()
    handler.setStream(stream)
    logging.getLogger("netforge.test").info("ping")
    output = stream.getvalue()
    assert "ping" in output
    if fmt == "text":
        # The filter populated the placeholder with the no-request sentinel.
        assert "[rid=-]" in output
    else:
        assert json.loads(output)["msg"] == "ping"
    configure_logging("info", "text")
