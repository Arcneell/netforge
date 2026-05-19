"""Map the request's Accept-Language to a prompt instruction.

We don't pull a full BCP-47 parser in for two locales — the UI only ever
sends "fr" or "en" today. Anything else (browser-set Accept-Language with
weighted alternatives, IDE testing, missing header) falls back to English
so the model has an unambiguous instruction.

Keeps the language-of-reply concern out of every service file: the routes
build a `language_instruction` string from the header and the AI services
append it to their system prompt.
"""

from __future__ import annotations

# Human-readable language names we hand to the model. The model is fluent in
# both — adding new languages here only needs the entry, no other code change.
_LANG_NAMES = {
    "fr": "French",
    "en": "English",
}

_FALLBACK = "en"


def _parse_primary_tag(accept_language: str | None) -> str:
    """Pick the highest-priority language tag from an Accept-Language header.

    Real browsers send e.g. "fr-FR,fr;q=0.9,en;q=0.8". We don't need the
    weight logic — the first tag wins for our two-locale UI. Strip region
    suffixes (`fr-FR` → `fr`) so an unusual locale code still matches.
    """
    if not accept_language:
        return _FALLBACK
    first = accept_language.split(",", 1)[0].strip().lower()
    primary = first.split("-", 1)[0].split(";", 1)[0].strip()
    return primary or _FALLBACK


def language_instruction(accept_language: str | None) -> str:
    """A single sentence to append to any AI system prompt."""
    tag = _parse_primary_tag(accept_language)
    name = _LANG_NAMES.get(tag, _LANG_NAMES[_FALLBACK])
    return (
        f"Reply in {name}. All titles, descriptions, recommendations and any "
        f"prose you produce must be in {name}. Keep entity names, IPs, CIDRs, "
        f"MAC addresses and hostnames in their original form — never translate them."
    )
