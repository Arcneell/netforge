"""Tests for the HIGH-priority provider hardening: explicit timeouts, a
typed rate-limit error distinct from the generic `AIProviderError`, and the
one-retry-on-rate-limit helper.

We stub the SDK modules rather than hitting real network calls — same
pattern `test_ai_providers_factory.py` already uses for the Anthropic
client build.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.ai.retry import call_with_retry
from app.services.ai.types import AIProviderError, AIProviderRateLimitError

# --- Timeout wiring ----------------------------------------------------


def test_anthropic_client_gets_a_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ai.providers.anthropic import AnthropicProvider

    captured: dict = {}

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys

    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic)
    )
    provider = AnthropicProvider(api_key="k", model="m")
    provider._get_client()
    assert captured.get("timeout") == pytest.approx(120.0)


def test_openai_client_gets_a_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ai.providers.openai import OpenAIProvider

    captured: dict = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys

    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
    )
    provider = OpenAIProvider(api_key="k", model="m")
    provider._get_client()
    assert captured.get("timeout") == pytest.approx(120.0)


def test_timeout_setting_is_read_via_getattr_with_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `ai_request_timeout_seconds` field exists on `Settings` yet — the
    provider must fall back to its own constant rather than crash, and must
    pick up the setting automatically once one is added (simulated here via
    a `SimpleNamespace` that DOES carry the field)."""
    from app.services.ai.providers import anthropic as anth_mod

    monkeypatch.setattr(
        anth_mod, "get_settings", lambda: SimpleNamespace(ai_request_timeout_seconds=45.0)
    )
    assert anth_mod._client_timeout_seconds() == 45.0

    monkeypatch.setattr(anth_mod, "get_settings", lambda: SimpleNamespace())
    assert anth_mod._client_timeout_seconds() == anth_mod._DEFAULT_TIMEOUT_SECONDS


def test_gemini_client_gets_a_configured_timeout_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`google-genai` is actually installed in this environment (used
    directly by the error-translation tests below), so rather than fight
    the real package's import machinery with a fake `sys.modules` entry,
    patch the real `genai.Client` class in place and inspect what it was
    constructed with."""
    from google import genai

    from app.services.ai.providers.gemini import GeminiProvider

    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeClient)

    provider = GeminiProvider(api_key="k", model="m")
    provider._get_client()
    http_options = captured.get("http_options")
    assert http_options is not None
    assert http_options.timeout == 120_000


# --- Typed rate-limit errors --------------------------------------------


def _httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code, request=httpx.Request("POST", "http://example.test")
    )


def test_anthropic_rate_limit_error_is_translated() -> None:
    import anthropic

    from app.services.ai.providers.anthropic import _translate_provider_error

    exc = anthropic.RateLimitError(
        "rate limited", response=_httpx_response(429), body=None
    )
    translated = _translate_provider_error(exc, context="anthropic API call failed")
    assert isinstance(translated, AIProviderRateLimitError)


def test_anthropic_overloaded_529_is_translated_as_rate_limit() -> None:
    """Anthropic's "overloaded_error" has no dedicated exception class — it
    surfaces as a plain `APIStatusError` with `status_code == 529`. Must
    still be treated as retryable/429, not a generic 502."""
    import anthropic

    from app.services.ai.providers.anthropic import _translate_provider_error

    exc = anthropic.APIStatusError(
        "overloaded", response=_httpx_response(529), body=None
    )
    translated = _translate_provider_error(exc, context="anthropic API call failed")
    assert isinstance(translated, AIProviderRateLimitError)


def test_anthropic_other_status_error_stays_generic() -> None:
    import anthropic

    from app.services.ai.providers.anthropic import _translate_provider_error

    exc = anthropic.APIStatusError(
        "bad request", response=_httpx_response(400), body=None
    )
    translated = _translate_provider_error(exc, context="anthropic API call failed")
    assert isinstance(translated, AIProviderError)
    assert not isinstance(translated, AIProviderRateLimitError)


def test_openai_rate_limit_error_is_translated() -> None:
    import openai

    from app.services.ai.providers.openai import _translate_provider_error

    exc = openai.RateLimitError("rate limited", response=_httpx_response(429), body=None)
    translated = _translate_provider_error(exc, context="openai API call failed")
    assert isinstance(translated, AIProviderRateLimitError)


def test_openai_other_error_stays_generic() -> None:
    import openai

    from app.services.ai.providers.openai import _translate_provider_error

    exc = openai.AuthenticationError(
        "bad key", response=_httpx_response(401), body=None
    )
    translated = _translate_provider_error(exc, context="openai API call failed")
    assert isinstance(translated, AIProviderError)
    assert not isinstance(translated, AIProviderRateLimitError)


def test_gemini_429_client_error_is_translated() -> None:
    from google.genai import errors as genai_errors

    from app.services.ai.providers.gemini import _translate_provider_error

    exc = genai_errors.ClientError(429, {"error": {"message": "rate limited"}})
    translated = _translate_provider_error(exc, context="gemini API call failed")
    assert isinstance(translated, AIProviderRateLimitError)


def test_gemini_other_client_error_stays_generic() -> None:
    from google.genai import errors as genai_errors

    from app.services.ai.providers.gemini import _translate_provider_error

    exc = genai_errors.ClientError(400, {"error": {"message": "bad request"}})
    translated = _translate_provider_error(exc, context="gemini API call failed")
    assert isinstance(translated, AIProviderError)
    assert not isinstance(translated, AIProviderRateLimitError)


def test_generic_exception_stays_a_plain_provider_error() -> None:
    from app.services.ai.providers.anthropic import _translate_provider_error

    translated = _translate_provider_error(
        ConnectionError("boom"), context="anthropic API call failed"
    )
    assert isinstance(translated, AIProviderError)
    assert not isinstance(translated, AIProviderRateLimitError)


# --- App-level retry -----------------------------------------------------


@pytest.mark.asyncio
async def test_call_with_retry_retries_once_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def flaky_then_ok():
        calls["n"] += 1
        if calls["n"] == 1:
            raise AIProviderRateLimitError("slow down")
        return "ok"

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    result = await call_with_retry(flaky_then_ok)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_call_with_retry_gives_up_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def always_rate_limited():
        calls["n"] += 1
        raise AIProviderRateLimitError("still slow")

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    with pytest.raises(AIProviderRateLimitError):
        await call_with_retry(always_rate_limited)
    assert calls["n"] == 2  # one original attempt + exactly one retry


@pytest.mark.asyncio
async def test_call_with_retry_does_not_retry_non_rate_limit_errors() -> None:
    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        raise AIProviderError("not a rate limit")

    with pytest.raises(AIProviderError):
        await call_with_retry(boom)
    assert calls["n"] == 1
