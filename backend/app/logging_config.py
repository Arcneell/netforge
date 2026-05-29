"""Structured logging configuration.

Two modes, selected by `LOG_FORMAT`:

- ``text`` (default) — the original human-readable single-line format, now
  with the request id inlined as ``[rid=...]`` so a grep can follow one
  request across log lines.
- ``json`` — one JSON object per line (timestamp, level, logger, message, the
  current request id, and any structured ``extra`` fields). Lets a log
  aggregator (Loki / ELK / Datadog) index fields like ``status`` or
  ``duration_ms`` without regex-parsing the message.

The request id is propagated through a ContextVar set by the request
middleware, so every log emitted while handling a request — not just the
final access line — carries it.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

# Set by the request middleware (see app/main.py) at the start of each
# request and reset to None for work outside a request (scheduler, startup).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes present on every LogRecord. Anything else found on a record is a
# caller-supplied `extra=` field and gets emitted verbatim in JSON mode.
_STD_LOGRECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        # Promote structured extras (e.g. logger.info("...", extra={"status": 200})).
        for key, value in record.__dict__.items():
            if key not in _STD_LOGRECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _RequestIdFilter(logging.Filter):
    """Expose the current request id to the text formatter as %(request_id)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def configure_logging(level: str, fmt: str = "text") -> None:
    """Install a single root handler in the requested format. Idempotent:
    existing handlers are cleared first so repeated calls (tests, reloads)
    don't stack duplicates."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(_RequestIdFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s] %(message)s"
            )
        )
    root.addHandler(handler)
