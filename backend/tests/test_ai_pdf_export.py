"""Tests for the advisor PDF export.

We don't parse the resulting PDF — the contract this layer cares about is:
- Non-empty bytes that start with the PDF magic header.
- All Unicode quirks the LLM enjoys (em-dashes, curly quotes, emoji) get
  sanitised so the file actually renders, instead of crashing fpdf2 with a
  UnicodeEncodeError.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.models.ai import InsightCategory, InsightSeverity
from app.services.ai.pdf_export import (
    _CHAR_MAP,
    _safe,
    build_filename,
    render_advisor_report,
)


def _insight(
    *,
    title: str = "Demo insight",
    description: str = "Demo description",
    recommendation: str = "Demo recommendation",
    severity: InsightSeverity = InsightSeverity.warning,
    category: InsightCategory = InsightCategory.naming,
    entities: list | None = None,
):
    return SimpleNamespace(
        title=title,
        description=description,
        recommendation=recommendation,
        severity=severity,
        category=category,
        affected_entities=entities or [],
    )


def test_safe_replaces_em_dash_and_curly_quotes() -> None:
    assert "—" in _CHAR_MAP
    assert "—" not in _safe("Hello — world")
    assert _safe("'curly' \"quotes\" — done…") == "'curly' \"quotes\" - done..."


def test_safe_handles_emoji_without_raising() -> None:
    """Anything outside Latin-1 must come back encoded — empty string OK,
    not a crash. fpdf2's default Helvetica can't render emoji at all, but the
    PDF must still render."""
    out = _safe("🚀 launch")
    # No exception, length non-zero, no unicode emoji left in.
    assert out and "🚀" not in out


def test_render_returns_pdf_bytes_with_magic_header() -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    insights = [
        _insight(severity=InsightSeverity.critical, title="Single core switch"),
        _insight(severity=InsightSeverity.warning, title="Subnet 92% full"),
        _insight(severity=InsightSeverity.info, title="Inconsistent naming"),
    ]
    out = render_advisor_report(run_created_at=now, insights=insights, locale="en")
    assert isinstance(out, bytes | bytearray)
    assert len(out) > 1000  # well above an empty header.
    assert out.startswith(b"%PDF-")


def test_render_handles_empty_insight_list() -> None:
    """A run that returned zero insights still produces a valid PDF — the
    summary table is empty but the document renders cleanly."""
    out = render_advisor_report(run_created_at=None, insights=[], locale="en")
    assert out.startswith(b"%PDF-")


def test_render_locale_french_falls_through_safely() -> None:
    """We embed FR + EN labels; an unknown locale falls back to EN without
    raising."""
    out = render_advisor_report(
        run_created_at=None,
        insights=[_insight()],
        locale="zz-ZZ",
    )
    assert out.startswith(b"%PDF-")


def test_render_with_chars_outside_latin1_does_not_crash() -> None:
    """Recommendations + descriptions from the LLM occasionally include
    bullet glyphs and arrows — verify the sanitiser keeps the PDF alive."""
    quirky = _insight(
        title="VLAN naming → migrate",
        description="• gateway A ↔ gateway B\n• avoid “quotes”",
        recommendation="• replace — done?",
    )
    out = render_advisor_report(
        run_created_at=datetime.now(UTC), insights=[quirky], locale="fr"
    )
    assert out.startswith(b"%PDF-")


def test_build_filename_falls_back_when_no_timestamp() -> None:
    assert build_filename(None).endswith(".pdf")
    when = datetime(2026, 5, 19, tzinfo=UTC)
    name = build_filename(when)
    assert "2026-05-19" in name
    assert name.endswith(".pdf")
