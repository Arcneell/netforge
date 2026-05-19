"""Tests for the Accept-Language → prompt instruction shim."""

from __future__ import annotations

import pytest

from app.services.ai.locale import _parse_primary_tag, language_instruction


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, "en"),
        ("", "en"),
        ("fr", "fr"),
        ("FR", "fr"),
        ("fr-FR,fr;q=0.9,en;q=0.8", "fr"),
        ("en-US", "en"),
        ("xx-YY", "xx"),  # unknown — falls through to the raw primary tag.
        # The weight syntax must be tolerated even when the primary tag carries one.
        ("fr;q=1.0,en;q=0.5", "fr"),
    ],
)
def test_parse_primary_tag(header: str | None, expected: str) -> None:
    assert _parse_primary_tag(header) == expected


def test_language_instruction_returns_french_for_fr_headers() -> None:
    out = language_instruction("fr-FR,fr;q=0.9")
    assert "French" in out
    # The "never translate names/IPs" caveat is the part that matters at runtime.
    assert "never translate" in out.lower()


def test_language_instruction_falls_back_to_english() -> None:
    assert "English" in language_instruction(None)
    # Unknown tag → still English (no FrenchAcadian, no garbled language name).
    assert "English" in language_instruction("xx-YY")
