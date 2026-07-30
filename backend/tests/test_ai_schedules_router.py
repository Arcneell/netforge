"""Tests for the `/api/ai/schedules` router — specifically the MEDIUM audit
fix: neither route called `_require_ai_enabled()`, so the schedules surface
stayed reachable (list AND write) even with `AI_ENABLED=false`, unlike
every other AI router."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.routers.ai import schedules as sched_router


def _settings(*, ai_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(ai_enabled=ai_enabled, webhook_allow_private_targets=False)


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


@pytest.mark.asyncio
async def test_list_schedules_404_when_ai_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.routers.ai.common.get_settings", lambda: _settings(ai_enabled=False)
    )
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await sched_router.list_schedules(db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_schedules_ok_when_ai_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.routers.ai.common.get_settings", lambda: _settings(ai_enabled=True)
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars([]))
    result = await sched_router.list_schedules(db=db)
    assert result == []


@pytest.mark.asyncio
async def test_upsert_schedule_404_when_ai_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: this write endpoint was reachable even with the master
    AI switch off — it never called `_require_ai_enabled()` at all."""
    monkeypatch.setattr(
        "app.routers.ai.common.get_settings", lambda: _settings(ai_enabled=False)
    )
    db = AsyncMock()
    payload = SimpleNamespace(
        webhook_url=None,
        enabled=True,
        interval_minutes=60,
        webhook_severity_threshold="warning",
    )
    with pytest.raises(HTTPException) as exc:
        await sched_router.upsert_schedule("advisor", payload, db=db)
    assert exc.value.status_code == 404
