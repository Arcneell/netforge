"""PDF export of the latest advisor report.

`fpdf2` rather than `WeasyPrint`: the latter is much nicer for HTML/CSS-
driven layouts but pulls in libcairo, libpango and friends, which would
fatten the backend image considerably for an endpoint that ships once a
month. fpdf2 is pure-Python, no native deps, and the advisor layout is
plain enough (severity groups + cards) that we don't lose much.

Layout:
- Title + generated-at line.
- Severity counts strip.
- For each severity (critical / warning / info), a section with one
  block per insight: bold title, two-column "Category / Affected" header,
  description paragraph, recommendation paragraph, entity chips line.
- Page numbers in the footer.

Localisation: the document is rendered in the language the operator's
header asked for. Falls back to English when no locale is given.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from fpdf import FPDF

from app.models.ai import InfraInsight, InsightSeverity

# Severity → display label. We don't tie this to the i18n bundle because
# the bundle is owned by the frontend; for a PDF that ships standalone, a
# minimal embedded translation keeps the file dependency-free.
_SEVERITY_LABELS = {
    "en": {"critical": "Critical", "warning": "Warning", "info": "Info"},
    "fr": {"critical": "Critique", "warning": "Avertissement", "info": "Info"},
}
_SECTION_TITLES = {
    "en": {"report": "AI advisor report", "generated": "Generated", "summary": "Summary"},
    "fr": {"report": "Rapport du conseiller IA", "generated": "Généré le", "summary": "Synthèse"},
}
_FIELD_LABELS = {
    "en": {
        "category": "Category",
        "recommendation": "Recommendation",
        "affected": "Affected entities",
        "no_recommendation": "(no recommendation)",
        "page": "Page",
    },
    "fr": {
        "category": "Catégorie",
        "recommendation": "Recommandation",
        "affected": "Entités concernées",
        "no_recommendation": "(aucune recommandation)",
        "page": "Page",
    },
}

# fpdf2 ships with a "core14" font (Helvetica) that handles Latin-1 but
# stumbles on chars like the en-dash and curly quotes that the LLM
# enjoys. We pre-substitute those at write time to keep the font dependency
# zero — adding a TTF would mean shipping a font file with the image.
_CHAR_MAP = {
    "—": "-",
    "–": "-",
    "…": "...",
    "•": "*",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "→": "->",
    "↔": "<->",
}


def _safe(text: str) -> str:
    """Replace chars the default Helvetica font can't encode + strip the
    rest down to Latin-1. The Anthropic/OpenAI tools occasionally emit a
    stray emoji; replacing them with `?` is better than crashing the PDF."""
    if not text:
        return ""
    for src, dst in _CHAR_MAP.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


class _AdvisorPDF(FPDF):
    """Subclass that owns the footer (page numbers). Keeping the header in
    `render_*` methods on the service module rather than overriding
    `header()` lets us draw a one-shot title page without a recurring
    header on every page."""

    def __init__(self, locale: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.locale = locale if locale in _SECTION_TITLES else "en"
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margin(15)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        page_text = f"{_FIELD_LABELS[self.locale]['page']} {self.page_no()} / {{nb}}"
        self.cell(0, 8, page_text, align="C")


def _severity_label(sev: InsightSeverity, locale: str) -> str:
    return _SEVERITY_LABELS.get(locale, _SEVERITY_LABELS["en"])[sev.value]


def _color_for(sev: InsightSeverity) -> tuple[int, int, int]:
    return {
        InsightSeverity.critical: (200, 30, 30),
        InsightSeverity.warning: (200, 130, 0),
        InsightSeverity.info: (40, 100, 200),
    }[sev]


def render_advisor_report(
    *,
    run_created_at: datetime | None,
    insights: list[InfraInsight],
    locale: str = "en",
) -> bytes:
    """Render a PDF and return the raw bytes. The route layer wraps that
    in a `StreamingResponse`."""
    pdf = _AdvisorPDF(locale=locale)
    pdf.alias_nb_pages()  # so `{nb}` in the footer resolves to total pages.
    pdf.add_page()
    locale_key = pdf.locale

    # --- Title ---
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 12, _safe(_SECTION_TITLES[locale_key]["report"]), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(110, 110, 110)
    when = run_created_at.strftime("%Y-%m-%d %H:%M UTC") if run_created_at else "—"
    pdf.cell(0, 6, _safe(f"{_SECTION_TITLES[locale_key]['generated']}: {when}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Summary line ---
    counts = {InsightSeverity.critical: 0, InsightSeverity.warning: 0, InsightSeverity.info: 0}
    for i in insights:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 7, _safe(_SECTION_TITLES[locale_key]["summary"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for sev in (InsightSeverity.critical, InsightSeverity.warning, InsightSeverity.info):
        r, g, b = _color_for(sev)
        pdf.set_text_color(r, g, b)
        pdf.cell(40, 6, _safe(f"{_severity_label(sev, locale_key)}: {counts.get(sev, 0)}"))
    pdf.ln(10)

    # --- Insight cards, grouped by severity ---
    for sev in (InsightSeverity.critical, InsightSeverity.warning, InsightSeverity.info):
        group = [i for i in insights if i.severity == sev]
        if not group:
            continue
        # Section heading
        pdf.set_font("Helvetica", "B", 13)
        r, g, b = _color_for(sev)
        pdf.set_text_color(r, g, b)
        pdf.cell(
            0,
            8,
            _safe(f"{_severity_label(sev, locale_key)} ({len(group)})"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(1)
        for ins in group:
            _render_card(pdf, ins, locale_key)

    return bytes(pdf.output())


def _render_card(pdf: _AdvisorPDF, ins: InfraInsight, locale: str) -> None:
    """One insight block. Page-break behaviour is handled by fpdf's
    auto_page_break + the `set_auto_page_break` we set up — `multi_cell`
    breaks across pages cleanly."""
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, _safe(ins.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0,
        5,
        _safe(f"{_FIELD_LABELS[locale]['category']}: {ins.category.value}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    # Description
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 10)
    if ins.description:
        pdf.multi_cell(0, 5, _safe(ins.description), new_x="LMARGIN", new_y="NEXT")
    # Recommendation
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(20, 70, 150)
    pdf.cell(
        0,
        5,
        _safe(f"{_FIELD_LABELS[locale]['recommendation']}:"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(60, 60, 60)
    rec = ins.recommendation or _FIELD_LABELS[locale]["no_recommendation"]
    pdf.multi_cell(0, 5, _safe(rec), new_x="LMARGIN", new_y="NEXT")
    # Affected entities — single line, comma-joined
    if ins.affected_entities:
        chips: list[str] = []
        for e in ins.affected_entities or []:
            if not isinstance(e, dict):
                continue
            name = (e.get("name") or "").strip() or f"{e.get('type', '?')} #{e.get('id', '?')}"
            chips.append(name)
        if chips:
            pdf.set_text_color(120, 120, 120)
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(
                0,
                5,
                _safe(f"{_FIELD_LABELS[locale]['affected']}: " + ", ".join(chips)),
                new_x="LMARGIN",
                new_y="NEXT",
            )
    pdf.ln(2)


def build_filename(run_created_at: datetime | None) -> str:
    """Suggested Content-Disposition filename."""
    when = run_created_at.strftime("%Y-%m-%d") if run_created_at else "report"
    return f"netforge-advisor-{when}.pdf"


# Tiny re-export keeping the import surface stable for tests.
__all__ = ["_CHAR_MAP", "BytesIO", "_safe", "build_filename", "render_advisor_report"]
