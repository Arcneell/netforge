"""Tests for the CORS-wildcard boot guard in `app.main.create_app`.

Same posture as the PUBLIC_URL guard in `app/auth/dev.py`: a known-bad
config must refuse to boot rather than silently run insecurely.
`allow_credentials=True` is hardcoded in `create_app` (every route relies
on the session cookie / Bearer token), so a wildcard entry in CORS_ORIGINS
must never reach `CORSMiddleware`.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    """`get_settings` is `lru_cache`d, so env changes need a fresh read.

    Clear both before and after so this test never leaks a cached Settings
    instance into a test that runs after it.
    """
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    get_settings.cache_clear()


def test_create_app_refuses_wildcard_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app()


def test_create_app_refuses_wildcard_mixed_with_real_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A wildcard anywhere in the list is enough to poison the whole CORS
    # policy — reject it even if explicit origins are also present.
    monkeypatch.setenv("CORS_ORIGINS", "https://netforge.example.local,*")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app()


def test_create_app_allows_explicit_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    app = create_app()
    assert app is not None


def test_create_app_allows_empty_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "")
    app = create_app()
    assert app is not None
