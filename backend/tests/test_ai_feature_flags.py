"""Tests for the granular AI feature toggles.

The master `AI_ENABLED` already gates every LLM-touching endpoint; these
sub-flags let an admin keep some surfaces but disable others (drafts is
the highest-risk one, scheduler is the auto-fire one).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.ai import _require_drafts_enabled
from app.services.ai import scheduler


def _settings(*, ai_enabled: bool, drafts: bool = True, sched: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        ai_enabled=ai_enabled,
        ai_drafts_enabled=drafts,
        ai_scheduler_enabled=sched,
    )


def test_require_drafts_enabled_passes_when_both_flags_true() -> None:
    with patch("app.routers.ai.get_settings", return_value=_settings(ai_enabled=True)):
        # No exception → ok.
        _require_drafts_enabled()


def test_require_drafts_enabled_404_when_master_off() -> None:
    with patch(
        "app.routers.ai.get_settings",
        return_value=_settings(ai_enabled=False, drafts=True),
    ):
        with pytest.raises(HTTPException) as exc:
            _require_drafts_enabled()
        assert exc.value.status_code == 404


def test_require_drafts_enabled_404_when_subflag_off() -> None:
    with patch(
        "app.routers.ai.get_settings",
        return_value=_settings(ai_enabled=True, drafts=False),
    ):
        with pytest.raises(HTTPException) as exc:
            _require_drafts_enabled()
        assert exc.value.status_code == 404


def test_start_scheduler_is_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifespan calls `start_scheduler()` unconditionally; this test
    verifies it short-circuits cleanly when AI_SCHEDULER_ENABLED=false
    rather than spinning a doomed task."""
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: _settings(ai_enabled=True, sched=False),
    )
    # Reset any previous task handle to make the assertion meaningful.
    monkeypatch.setattr(scheduler, "_TASK", None)
    scheduler.start_scheduler()
    assert scheduler._TASK is None
