"""Tests for the AI pricing lookup helpers."""

from __future__ import annotations

import pytest

from app.services.ai.pricing import estimate_cost_usd, get_rate


def test_known_model_returns_exact_rate() -> None:
    assert get_rate("anthropic", "claude-sonnet-4-6") == (3.00, 15.00)
    assert get_rate("openai", "gpt-4o-mini") == (0.15, 0.60)
    assert get_rate("gemini", "gemini-2.5-flash") == (0.075, 0.30)


def test_unknown_model_falls_back_to_provider_default() -> None:
    """A brand-new model the operator wired up before the table caught up
    should not break the page — fall back to a reasonable provider default."""
    assert get_rate("anthropic", "claude-future-model-99") == (3.00, 15.00)
    assert get_rate("openai", "gpt-5") == (2.50, 10.00)


def test_unknown_provider_returns_none() -> None:
    assert get_rate("nonexistent", "x") is None


def test_provider_lookup_is_case_insensitive() -> None:
    assert get_rate("Anthropic", "claude-sonnet-4-6") == (3.00, 15.00)
    assert get_rate("OPENAI", "gpt-4o") == (2.50, 10.00)


@pytest.mark.parametrize(
    "in_tokens,out_tokens,expected",
    [
        (0, 0, 0.0),
        # 1M in @ $3 = $3
        (1_000_000, 0, 3.0),
        # 1M in + 1M out @ $3/$15 = $18
        (1_000_000, 1_000_000, 18.0),
        # 100 in + 50 out — fractional cents.
        (100, 50, (100 / 1_000_000) * 3.0 + (50 / 1_000_000) * 15.0),
    ],
)
def test_estimate_cost_for_anthropic_sonnet(
    in_tokens: int, out_tokens: int, expected: float
) -> None:
    got = estimate_cost_usd(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=in_tokens,
        completion_tokens=out_tokens,
    )
    assert got == pytest.approx(expected)


def test_estimate_unknown_provider_is_zero() -> None:
    assert estimate_cost_usd(
        provider="nope", model="x", prompt_tokens=10_000, completion_tokens=10_000
    ) == 0.0
