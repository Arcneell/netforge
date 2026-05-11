"""Tests for cookie helpers in app.auth.sessions."""

from unittest.mock import MagicMock

from fastapi import Response

from app.auth.sessions import (
    clear_session_cookie,
    get_session_id_from_cookie,
    set_session_cookie,
)
from app.config import Settings


def _settings(secure: bool = False) -> Settings:
    return Settings(
        session_cookie_name="netforge_session",
        session_max_age_seconds=3600,
        session_cookie_secure=secure,
    )


def test_set_session_cookie_in_dev_uses_http_attrs() -> None:
    response = Response()
    set_session_cookie(response, "sess-abc", _settings(secure=False))

    raw = response.headers.get("set-cookie", "")
    assert "netforge_session=sess-abc" in raw
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw
    assert "Max-Age=3600" in raw
    # In dev we do not want Secure (HTTP localhost).
    assert "Secure" not in raw


def test_set_session_cookie_in_prod_sets_secure() -> None:
    response = Response()
    set_session_cookie(response, "sess-xyz", _settings(secure=True))

    raw = response.headers.get("set-cookie", "")
    assert "Secure" in raw


def test_clear_session_cookie_emits_expired_max_age() -> None:
    response = Response()
    clear_session_cookie(response, _settings(secure=False))

    raw = response.headers.get("set-cookie", "")
    assert "netforge_session=" in raw
    assert ("Max-Age=0" in raw) or ("expires=" in raw.lower())


def test_get_session_id_from_cookie_returns_value() -> None:
    request = MagicMock()
    request.cookies = {"netforge_session": "sess-123"}
    assert get_session_id_from_cookie(request, _settings()) == "sess-123"


def test_get_session_id_from_cookie_returns_none_when_missing() -> None:
    request = MagicMock()
    request.cookies = {}
    assert get_session_id_from_cookie(request, _settings()) is None
