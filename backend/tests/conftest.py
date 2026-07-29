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
