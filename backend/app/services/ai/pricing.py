"""Public-list pricing for the supported (provider, model) pairs.

We embed the rates in code because:
- They change infrequently (quarterly at most).
- A live "fetch the price page" call adds an external dependency for what is
  essentially a static lookup.
- The values are an estimate anyway — actual invoicing differs slightly
  (cache hits are cheaper, batch is 50 % off, region surcharges exist).

If you need precise accounting, plug a real billing source on top of this
module — the rest of the code only depends on `estimate_cost_usd`.

Last reviewed: 2026-07-29. Rates are USD per 1M tokens.
"""

from __future__ import annotations

# (provider, model) → (input_usd_per_million, output_usd_per_million)
# Wildcards are stored as `(provider, "")` and used as a fallback when the
# exact model isn't recognised — keeps the page useful for new models the
# operator wires up before this table is updated.
_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # Anthropic — https://www.anthropic.com/pricing
    # Sonnet 5 lists at 3.00/15.00; an introductory 2.00/10.00 runs through
    # 2026-08-31, so this over-estimates slightly until then.
    ("anthropic", "claude-sonnet-5"): (3.00, 15.00),
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-opus-5"): (5.00, 25.00),
    ("anthropic", "claude-opus-4-8"): (5.00, 25.00),
    ("anthropic", "claude-opus-4-7"): (5.00, 25.00),
    ("anthropic", "claude-fable-5"): (10.00, 50.00),
    ("anthropic", "claude-haiku-4-5"): (1.00, 5.00),
    ("anthropic", ""): (3.00, 15.00),  # default to Sonnet pricing
    # OpenAI — https://openai.com/api/pricing
    ("openai", "gpt-5.5"): (5.00, 30.00),
    ("openai", "gpt-5.4"): (2.50, 15.00),
    ("openai", "gpt-4o"): (2.50, 10.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", ""): (5.00, 30.00),  # default to the current flagship
    # Google Gemini — https://ai.google.dev/gemini-api/docs/pricing
    # Gemini charges a higher tier above a 200K-token prompt (2.5-pro moves to
    # 2.50/15.00, 3.1-pro to 4.00/18.00). We bill the standard tier: the
    # snapshot cap in `context.py` keeps prompts well under 200K.
    ("gemini", "gemini-2.5-pro"): (1.25, 10.00),
    ("gemini", "gemini-2.5-flash"): (0.075, 0.30),
    ("gemini", "gemini-3.1-pro-preview"): (2.00, 12.00),
    ("gemini", ""): (1.25, 10.00),
}

# Cache multipliers, applied to the INPUT rate above — same structure for
# every provider/model since all three vendors price prompt caching as a
# multiplier of the base input rate rather than a separate flat rate.
# Anthropic publishes these ratios explicitly; OpenAI/Gemini auto-cache at
# comparable ratios. Not yet wired into `estimate_cost_usd` (no caller
# tracks cache-read/cache-write token counts separately today — see
# `AIRunLog` / `TokenUsage`, which only carry prompt/completion totals) —
# exposed here so a future caller doesn't have to reverse-engineer the
# ratio.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


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
