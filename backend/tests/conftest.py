"""Unit-suite defaults.

The rate limiters default to `RATE_LIMIT_STORE=database`, i.e. they count
in the `rate_limit_counters` table so workers and replicas share one
budget. The unit suite has no database: several modules import
`app.main.app` (whose middleware stack is built at import time) and drive
writes through it, which would otherwise either stall on a connection
attempt or — worse, on a developer box with the dev Postgres running —
consume a real shared budget and make a second `pytest` run inside the same
minute collect 429s.

Forcing "memory" here keeps the unit suite hermetic and deterministic. The
DB-backed path is covered by `tests/test_rate_limit_store.py` (mocked
engine) and `tests/integration/test_rate_limit_shared_pg.py` (real
Postgres). This must run before anything imports `app.config`, which
conftest collection guarantees.
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMIT_STORE", "memory")

# Imported after the env default above, which has to be set before anything
# pulls in `app.config`.
import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limit_window():
    """Give every test a fresh process-local rate-limit window.

    In "memory" mode the counters live in one process-global window, and the
    imported `app.main.app` is shared by every module that drives HTTP through
    it. Without this reset the window is cumulative across the whole run: a
    test that issues writes passes on its own and collects a 429 in the full
    suite purely because of how many tests ran before it. The failure looks
    like a bug in the test under scrutiny and is actually about ordering, so
    it costs far more to debug than it does to prevent.

    Deliberately per-test rather than per-module: the cap is 60 writes per 60
    seconds, and a single module's bulk-import cases can approach that alone.
    """
    from app.middleware.rate_limit import reset_fallback_windows

    reset_fallback_windows()
    yield
    reset_fallback_windows()
