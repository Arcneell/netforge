"""Public-list pricing for the supported (provider, model) pairs.

We embed the rates in code because:
- They change infrequently (quarterly at most).
- A live "fetch the price page" call adds an external dependency for what is
  essentially a static lookup.
- The values are an estimate anyway — actual invoicing differs slightly
  (cache hits are cheaper, batch is 50 % off, region surcharges exist).

If you need precise accounting, plug a real billing source on top of this
module — the rest of the code only depends on `estimate_cost_usd`.

Last reviewed: 2026-05-19. Rates are USD per 1M tokens.
"""

from __future__ import annotations

# (provider, model) → (input_usd_per_million, output_usd_per_million)
# Wildcards are stored as `(provider, "")` and used as a fallback when the
# exact model isn't recognised — keeps the page useful for new models the
# operator wires up before this table is updated.
_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # Anthropic — https://www.anthropic.com/pricing
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-opus-4-7"): (15.00, 75.00),
    ("anthropic", "claude-haiku-4-5"): (0.80, 4.00),
    ("anthropic", ""): (3.00, 15.00),  # default to Sonnet pricing
    # OpenAI — https://openai.com/api/pricing
    ("openai", "gpt-4o"): (2.50, 10.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", ""): (2.50, 10.00),
    # Google Gemini — https://ai.google.dev/gemini-api/docs/pricing
    ("gemini", "gemini-2.5-pro"): (1.25, 5.00),
    ("gemini", "gemini-2.5-flash"): (0.075, 0.30),
    ("gemini", ""): (1.25, 5.00),
}


def get_rate(provider: str, model: str) -> tuple[float, float] | None:
    """Lookup `(in_$/M, out_$/M)` for a (provider, model). Returns None when
    the provider is unknown — caller decides whether to treat that as a 0$
    estimate or hide the column."""
    key = (provider.lower(), model)
    if key in _PRICING:
        return _PRICING[key]
    fallback = (provider.lower(), "")
    return _PRICING.get(fallback)


def estimate_cost_usd(
    *, provider: str, model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """USD cost estimate for one call. Returns 0.0 if the (provider, model)
    is unknown — the UI surfaces an "n/a" badge in that case rather than
    pretending the call was free."""
    rate = get_rate(provider, model)
    if rate is None:
        return 0.0
    in_rate, out_rate = rate
    return (prompt_tokens / 1_000_000.0) * in_rate + (completion_tokens / 1_000_000.0) * out_rate
