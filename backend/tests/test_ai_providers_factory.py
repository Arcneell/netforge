"""Tests for the AI provider factory + per-process instance cache."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.ai import providers as factory


def _settings(provider: str = "anthropic") -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider=provider,
        ai_model="",
        ai_anthropic_api_key="anth-key",
        ai_openai_api_key="oai-key",
        ai_gemini_api_key="gem-key",
    )


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings("nope"))
    factory.reset_provider_cache()
    with pytest.raises(factory.AIProviderError):
        factory.get_provider()


def test_provider_instance_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two `get_provider()` calls with the same settings must return the same
    instance — keeps the SDK client + httpx pool warm between requests."""
    monkeypatch.setattr(factory, "get_settings", lambda: _settings("anthropic"))
    factory.reset_provider_cache()
    # Stub the AnthropicProvider class so we don't depend on the SDK install.
    captured: list[dict] = []

    class FakeProvider:
        name = "anthropic"

        def __init__(self, *, api_key: str, model: str) -> None:
            captured.append({"api_key": api_key, "model": model})
            self.model = model

    import app.services.ai.providers.anthropic as anth_mod

    monkeypatch.setattr(anth_mod, "AnthropicProvider", FakeProvider)
    a = factory.get_provider()
    b = factory.get_provider()
    assert a is b, "factory should hand back the cached instance"
    assert len(captured) == 1


def test_reset_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings("anthropic"))
    factory.reset_provider_cache()

    class FakeProvider:
        name = "anthropic"

        def __init__(self, *, api_key: str, model: str) -> None:
            self.model = model

    import app.services.ai.providers.anthropic as anth_mod

    monkeypatch.setattr(anth_mod, "AnthropicProvider", FakeProvider)
    a = factory.get_provider()
    factory.reset_provider_cache()
    b = factory.get_provider()
    assert a is not b


def test_concrete_providers_lazily_build_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_get_client` must memoise the SDK client on the instance — calling it
    twice returns the same object, even though `AsyncAnthropic` would be
    happy to build a fresh one each time."""
    from app.services.ai.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="anth-key", model="claude-test")

    sentinel = MagicMock()

    # Patch the import path used inside `_get_client`. Because the SDK is
    # imported lazily inside the method body, we monkeypatch the `anthropic`
    # module sys-side via the module-level attribute lookup.
    import sys

    fake_module = SimpleNamespace(AsyncAnthropic=lambda api_key, **_kwargs: sentinel)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    c1 = provider._get_client()
    c2 = provider._get_client()
    assert c1 is sentinel
    assert c2 is sentinel  # second call hits the cache
