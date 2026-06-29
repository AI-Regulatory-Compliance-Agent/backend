"""
PDF Generator Tool — Creates downloadable compliance report PDFs.

Used ONLY by the report_generator agent (Node 5) as the final step
of the analysis pipeline. Takes the structured report data and
generates a professional PDF document using ReportLab.

PDF Structure:
  Page 1:  Cover — full-bleed navy header, company name, risk badge, stat pills
           [External mode] — "🌐 External Research Mode" badge below the header
  Page 2:  Executive summary + stat cards + applicable regulations table
           [External mode] — methodology note about web research + confidence tags
  Page N:  Compliance gaps table (colour-coded risk column)
  Page N:  Remediation plan table
  Last:    Disclaimer + [External mode] methodology footer note

Design language:
  - Navy #0f2044 for headers/accents
  - Slate #1e3a5f for sub-headers
  - Light grey #f4f6f9 page background stripe on cover
  - Risk colours carried through consistently
  - Running page header (company name + report title) on pages 2+
  - Running page footer (page number + date + confidentiality notice)

Color coding:
  CRITICAL (80-100): #dc2626
  HIGH     (60-79):  #ea580c
  MEDIUM   (40-59):  #d97706
  LOW      (0-39):   #16a34a
"""

import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus.flowables import Flowable

# ── Brand palette ─────────────────────────────────────────────
NAVY        = colors.HexColor("#0f2044")
SLATE       = colors.HexColor("#1e3a5f")
ACCENT      = colors.HexColor("#2563eb")
LIGHT_BG    = colors.HexColor("#f4f6f9")
BORDER      = colors.HexColor("#d1d5db")
TEXT_DARK   = colors.HexColor("#111827")
TEXT_MID    = colors.HexColor("#374151")
TEXT_LIGHT  = colors.HexColor("#6b7280")
WHITE       = colors.white

# External Research Mode badge colour — teal to visually distinguish
# from the navy/blue brand palette
EXTERNAL_BADGE_BG   = colors.HexColor("#0e7490")   # cyan-700
EXTERNAL_BADGE_TEXT = colors.HexColor("#ecfeff")   # cyan-50

RISK_COLORS = {
    "CRITICAL": colors.HexColor("#dc2626"),
    "HIGH":     colors.HexColor("#ea580c"),
    "MEDIUM":   colors.HexColor("#d97706"),
    "LOW":      colors.HexColor("#16a34a"),
}
RISK_BG = {
    "CRITICAL": colors.HexColor("#fef2f2"),
    "HIGH":     colors.HexColor("#fff7ed"),
    "MEDIUM":   colors.HexColor("#fffbeb"),
    "LOW":      colors.HexColor("#f0fdf4"),
}
CONFIDENCE_COLORS = {
    "CONFIRMED": colors.HexColor("#16a34a"),
    "PROBABLE":  colors.HexColor("#d97706"),
    "UNKNOWN":   colors.HexColor("#dc2626"),
}

A4_W, A4_H = A4
L_MARGIN = R_MARGIN = 22 * mm
T_MARGIN = B_MARGIN = 22 * mm
CONTENT_W = A4_W - L_MARGIN - R_MARGIN   # ~551pt


# ── Colour band flowable ──────────────────────────────────────
class ColorBand(Flowable):
    """Full-width horizontal band of solid colour."""
    def __init__(self, height, fill_color, width=None):
        super().__init__()
        self._bw   = width or CONTENT_W
        self._bh   = height
        self._fill = fill_color

    def draw(self):
        self.canv.setFillColor(self._fill)
        self.canv.rect(0, 0, self._bw, self._bh, fill=1, stroke=0)

    def wrap(self, *args):
        return self._bw, self._bh


# ── Rounded-rect badge flowable ───────────────────────────────
class RiskBadge(Flowable):
    """Large centred risk-score badge: big number + label pill."""
    def __init__(self, score, level, width=None):
        super().__init__()
        self._score = score
        self._level = level
        self._w     = width or CONTENT_W
        self._h     = 120
        self._color = RISK_COLORS.get(level, colors.gray)
        self._bg    = RISK_BG.get(level, colors.HexColor("#f9fafb"))

    def draw(self):
        c = self.canv
        cx = self._w / 2

        # Outer rounded rect (card background)
        c.setFillColor(self._bg)
        c.setStrokeColor(self._color)
        c.setLineWidth(1.5)
        c.roundRect(cx - 110, 10, 220, 100, 12, fill=1, stroke=1)

        # Big score number
        c.setFillColor(self._color)
        c.setFont("Helvetica-Bold", 52)
        c.drawCentredString(cx, 72, str(self._score))

        # Risk level label (small pill)
        pill_w, pill_h, pill_r = 120, 22, 8
        pill_x = cx - pill_w / 2
        c.setFillColor(self._color)
        c.roundRect(pill_x, 18, pill_w, pill_h, pill_r, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, 24, f"RISK LEVEL: {self._level}")

    def wrap(self, *args):
        return self._w, self._h


# ── External Research Mode badge flowable ─────────────────────
class ExternalResearchBadge(Flowable):
    """
    Teal pill badge shown on the cover page when analysis_mode is "external".
    Signals to the reader that web research was used to gather information.
    """
    def __init__(self, width=None):
        super().__init__()
        self._w = width or CONTENT_W
        self._h = 32

    def draw(self):
        c  = self.canv
        cx = self._w / 2

        # Teal pill background
        pill_w, pill_h, pill_r = 260, 26, 10
        pill_x = cx - pill_w / 2
        c.setFillColor(EXTERNAL_BADGE_BG)
        c.roundRect(pill_x, 2, pill_w, pill_h, pill_r, fill=1, stroke=0)

        # Badge text
        c.setFillColor(EXTERNAL_BADGE_TEXT)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, 10, "\u2b24  EXTERNAL RESEARCH MODE  \u2b24")

    def wrap(self, *args):
        return self._w, self._h


# ── Stat pill row flowable ─────────────────────────────────────
class StatRow(Flowable):
    """Row of 4 stat pills: critical / high / medium / low counts."""
    def __init__(self, counts, width=None):
        super().__init__()
        self._counts = counts   # dict: {"CRITICAL":n, "HIGH":n, ...}
        self._w = width or CONTENT_W
        self._h = 58

    def draw(self):
        c    = self.canv
        keys = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        n    = len(keys)
        gap  = 10
        pw   = (self._w - gap * (n - 1)) / n

        for i, key in enumerate(keys):
            x   = i * (pw + gap)
            col = RISK_COLORS.get(key, colors.gray)
            bg  = RISK_BG.get(key, LIGHT_BG)

            # Pill background
            c.setFillColor(bg)
            c.setStrokeColor(col)
            c.setLineWidth(1)
            c.roundRect(x, 0, pw, self._h - 4, 8, fill=1, stroke=1)

            # Count
            c.setFillColor(col)
            c.setFont("Helvetica-Bold", 20)
            c.drawCentredString(x + pw / 2, 24, str(self._counts.get(key, 0)))

            # Label
            c.setFillColor(TEXT_MID)
            c.setFont("Helvetica", 7)
            c.drawCentredString(x + pw / 2, 10, key)

    def wrap(self, *args):
        return self._w, self._h


# ── Page header/footer canvas callback ────────────────────────
def _make_page_decorator(company_name, generated_at, analysis_mode):
    def _decorate(canvas, doc):
        if doc.page == 1:
            return   # cover page — no header/footer

        canvas.saveState()
        page_w, _ = A4

        # Header bar
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4_H - 14 * mm, page_w, 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(L_MARGIN, A4_H - 9 * mm, company_name.upper())
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(
            page_w - R_MARGIN, A4_H - 9 * mm,
            "AI REGULATORY COMPLIANCE GAP ANALYSIS REPORT"
        )

        # Footer bar
        canvas.setFillColor(LIGHT_BG)
        canvas.rect(0, 0, page_w, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(TEXT_LIGHT)
        canvas.setFont("Helvetica", 7)

        # In external mode, replace the confidentiality notice with a
        # methodology note reminding the reader that web research was used.
        if analysis_mode == "external":
            footer_text = (
                f"External Research Mode \u00b7 Findings tagged CONFIRMED / PROBABLE / UNKNOWN "
                f"\u00b7 Generated {generated_at} \u00b7 AI-assisted \u2014 not legal advice"
            )
        else:
            footer_text = (
                f"Confidential \u00b7 Generated {generated_at} "
                f"\u00b7 AI-assisted analysis \u2014 not legal advice"
            )

        canvas.drawString(L_MARGIN, 4 * mm, footer_text)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawRightString(
            page_w - R_MARGIN, 4 * mm, f"Page {doc.page}"
        )

        canvas.restoreState()

    return _decorate


# ── Helpers ───────────────────────────────────────────────────
def _cell(text, style):
    return Paragraph(str(text) if text is not None else "—", style)


def _section_header(title, styles):
    """Returns a KeepTogether block: left accent bar + section title."""
    # Accent stripe + title as a single-row table so they stay together
    title_para = Paragraph(title, styles["SectionTitle"])
    data = [[ColorBand(28, ACCENT, 4), title_para]]
    t = Table(data, colWidths=[8, CONTENT_W - 8])
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (1, 0), (1, 0),   10),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([Spacer(1, 14), t, Spacer(1, 8)])


# ── Main generator ────────────────────────────────────────────
def generate_pdf(report_data: dict) -> bytes:
    buffer       = io.BytesIO()
    generated_at = datetime.now().strftime("%B %d, %Y")

    company_name  = report_data.get("company_name", "Unknown Company")
    analysis_type = report_data.get("analysis_type", "product")
    analysis_mode = report_data.get("analysis_mode", "self")
    info_avail    = report_data.get("information_availability", "full")
    risk_score    = report_data.get("overall_risk_score", 0)
    risk_level    = report_data.get("overall_risk_level", "LOW")
    risk_range    = report_data.get("risk_score_range")
    confidence    = report_data.get("confidence_level", "full")
    regulations   = report_data.get("applicable_regulations", [])
    scored_gaps   = report_data.get("scored_gaps", [])
    remediations  = report_data.get("remediation_plan", [])
    is_external   = analysis_mode == "external"

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=R_MARGIN,
        leftMargin=L_MARGIN,
        topMargin=T_MARGIN + 14 * mm,   # extra room for header bar on inner pages
        bottomMargin=B_MARGIN + 12 * mm,
        title=f"Compliance Report — {company_name}",
        author="AI Regulatory Compliance Agent",
    )

    # ── Styles ────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle("CoverTag",    parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#93c5fd"),
        fontName="Helvetica", alignment=TA_CENTER, spaceBefore=0, spaceAfter=4))
    styles.add(ParagraphStyle("CoverCompany", parent=styles["Normal"],
        fontSize=32, textColor=WHITE, fontName="Helvetica-Bold",
        alignment=TA_CENTER, leading=38, spaceBefore=0, spaceAfter=6))
    styles.add(ParagraphStyle("CoverSub",    parent=styles["Normal"],
        fontSize=13, textColor=colors.HexColor("#bfdbfe"),
        fontName="Helvetica", alignment=TA_CENTER, spaceBefore=0, spaceAfter=0))
    styles.add(ParagraphStyle("CoverMeta",   parent=styles["Normal"],
        fontSize=9,  textColor=colors.HexColor("#94a3b8"),
        fontName="Helvetica", alignment=TA_CENTER))
    styles.add(ParagraphStyle("SectionTitle", parent=styles["Normal"],
        fontSize=13, fontName="Helvetica-Bold",
        textColor=NAVY, leading=18, spaceBefore=0, spaceAfter=0))
    styles.add(ParagraphStyle("Body",        parent=styles["Normal"],
        fontSize=9.5, leading=14, textColor=TEXT_MID,
        alignment=TA_JUSTIFY, spaceAfter=6))
    styles.add(ParagraphStyle("NoteBox",     parent=styles["Normal"],
        fontSize=9, leading=13, textColor=colors.HexColor("#92400e"),
        backColor=colors.HexColor("#fffbeb"), borderWidth=0,
        borderPadding=8, spaceAfter=8))
    # Teal note box for external research methodology note
    styles.add(ParagraphStyle("ExternalNoteBox", parent=styles["Normal"],
        fontSize=9, leading=13, textColor=colors.HexColor("#164e63"),
        backColor=colors.HexColor("#ecfeff"), borderWidth=0,
        borderPadding=8, spaceAfter=8))

    cell_s = ParagraphStyle("TC",   parent=styles["Normal"],
        fontSize=8, leading=11, textColor=TEXT_DARK)
    cell_b = ParagraphStyle("TCB",  parent=cell_s,
        fontName="Helvetica-Bold")
    cell_m = ParagraphStyle("TCM",  parent=cell_s,
        textColor=TEXT_LIGHT)
    hdr_s  = ParagraphStyle("TH",   parent=styles["Normal"],
        fontSize=8, leading=11, fontName="Helvetica-Bold",
        textColor=WHITE)

    BASE_TS = [
        ("BACKGROUND",    (0, 0), (-1, 0),  NAVY),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
    ]

    story = []

    # ════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ════════════════════════════════════════════════════════

    # Full-width navy header band (sits at top of content area)
    story.append(ColorBand(180, NAVY))

    # Overlay text on the band using a zero-height spacer trick:
    # we go back up by inserting the text into a table that has
    # a transparent background positioned over the band.
    cover_overlay = [
        [Paragraph("AI REGULATORY COMPLIANCE", styles["CoverTag"])],
        [Paragraph("Gap Analysis Report", styles["CoverCompany"])],
        [Paragraph(f"Prepared for {company_name}", styles["CoverSub"])],
        [Spacer(1, 6)],
        [Paragraph(
            f"{analysis_type.title()} Analysis &nbsp;·&nbsp; "
            f"{info_avail.title()} Information &nbsp;·&nbsp; {generated_at}",
            styles["CoverMeta"]
        )],
    ]
    # Place this table on top of the band by pulling it up
    story.append(Spacer(1, -160))   # move up to sit inside band
    for row in cover_overlay:
        story.append(row[0])

    story.append(Spacer(1, 24))

    # ── External Research Mode badge ─────────────────────────
    # Shown immediately below the cover band when mode is "external".
    # Uses a teal pill to visually distinguish from the navy brand palette.
    if is_external:
        story.append(ExternalResearchBadge())
        story.append(Spacer(1, 10))

    # Risk badge card
    story.append(RiskBadge(risk_score, risk_level))

    if risk_range and confidence != "full":
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Score Range: {risk_range.get('min','?')} – "
            f"{risk_range.get('max','?')}  "
            f"(Estimated: {risk_range.get('estimated','?')})",
            ParagraphStyle("RR", parent=styles["Normal"],
                fontSize=9, alignment=TA_CENTER, textColor=TEXT_LIGHT)
        ))

    story.append(Spacer(1, 28))

    # Cover metadata table (Analysis Type / Info Level / Confidence / Date)
    meta_label = ParagraphStyle("ML", parent=styles["Normal"],
        fontSize=8, fontName="Helvetica-Bold", textColor=TEXT_LIGHT)
    meta_value = ParagraphStyle("MV", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica-Bold", textColor=TEXT_DARK)

    # In external mode, replace "CONFIDENCE" with "RESEARCH MODE"
    meta_items = [
        ("ANALYSIS TYPE",     analysis_type.upper()),
        ("INFORMATION LEVEL", info_avail.upper()),
        ("RESEARCH MODE" if is_external else "CONFIDENCE",
         "EXTERNAL" if is_external else confidence.upper()),
        ("DATE",              generated_at),
    ]
    meta_cells = []
    for label, value in meta_items:
        meta_cells.append(
            Table(
                [[Paragraph(label, meta_label)],
                 [Paragraph(value, meta_value)]],
                colWidths=[(CONTENT_W - 30) / 4]
            )
        )
    meta_row = Table(
        [meta_cells],
        colWidths=[(CONTENT_W - 30) / 4] * 4,
        hAlign="CENTER"
    )
    meta_row.setStyle(TableStyle([
        ("LINEABOVE",     (0, 0), (-1, 0), 1, BORDER),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_row)

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════
    # PAGE 2 — EXECUTIVE SUMMARY
    # ════════════════════════════════════════════════════════
    story.append(_section_header("Executive Summary", styles))

    critical_count = sum(1 for g in scored_gaps if g.get("risk_level") == "CRITICAL")
    high_count     = sum(1 for g in scored_gaps if g.get("risk_level") == "HIGH")
    medium_count   = sum(1 for g in scored_gaps if g.get("risk_level") == "MEDIUM")
    low_count      = sum(1 for g in scored_gaps if g.get("risk_level") == "LOW")

    story.append(Paragraph(
        f"This report presents the regulatory compliance gap analysis for "
        f"<b>{company_name}</b>, conducted in <b>{analysis_type}</b> mode "
        f"with <b>{info_avail}</b> information availability. "
        f"A total of <b>{len(regulations)}</b> applicable regulations were "
        f"identified, with <b>{len(scored_gaps)}</b> compliance gaps found.",
        styles["Body"]
    ))

    # ── External Research methodology note ───────────────────
    # Shown in teal to distinguish from the amber partial-info warning.
    # Placed before the amber warning so reading order is:
    # 1. What mode was used  2. What the uncertainty means
    if is_external:
        story.append(Paragraph(
            "<b>\u2b24 External Research Mode:</b> This report was generated "
            "using external web research. The AI agents searched publicly "
            "available sources to gather information about this company before "
            "performing the analysis. Findings are tagged with confidence levels: "
            "<b>CONFIRMED</b> (publicly verifiable), "
            "<b>PROBABLE</b> (inferred from public data or industry norms), "
            "and <b>UNKNOWN</b> (cannot be determined from public information). "
            "Consult with qualified legal professionals before acting on these findings.",
            styles["ExternalNoteBox"]
        ))

    if confidence != "full":
        story.append(Paragraph(
            f"⚠  This analysis was conducted with {info_avail} information "
            f"availability. Gaps tagged PROBABLE should be verified against "
            f"internal company documentation before remediation is prioritised.",
            styles["NoteBox"]
        ))

    # Stat pills
    story.append(Spacer(1, 10))
    story.append(StatRow({"CRITICAL": critical_count, "HIGH": high_count,
                          "MEDIUM": medium_count, "LOW": low_count}))
    story.append(Spacer(1, 20))

    # ── Applicable Regulations ────────────────────────────────
    story.append(_section_header("Applicable Regulations", styles))

    if regulations:
        REG_COLS = [24, 160, 255, 82]   # sum = 521 ✓
        reg_rows = [[
            _cell("#", hdr_s), _cell("Regulation", hdr_s),
            _cell("Relevance", hdr_s), _cell("Confidence", hdr_s),
        ]]
        for i, reg in enumerate(regulations, 1):
            ctag   = reg.get("confidence", "N/A")
            ccol   = CONFIDENCE_COLORS.get(ctag, TEXT_LIGHT)
            cs     = ParagraphStyle(f"C{i}", parent=cell_s,
                                    textColor=ccol, fontName="Helvetica-Bold")
            reg_rows.append([
                _cell(str(i), cell_m),
                _cell(reg.get("name", "N/A"), cell_b),
                _cell(reg.get("relevance", "N/A"), cell_s),
                _cell(ctag, cs),
            ])
        reg_t = Table(reg_rows, colWidths=REG_COLS, repeatRows=1)
        reg_t.setStyle(TableStyle(BASE_TS))
        story.append(reg_t)
    else:
        story.append(Paragraph("No applicable regulations identified.", styles["Body"]))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════
    # COMPLIANCE GAPS
    # ════════════════════════════════════════════════════════
    story.append(_section_header("Compliance Gaps", styles))

    if scored_gaps:
        # In external mode, add a "Score Range" column to show uncertainty
        if is_external:
            GAP_COLS = [22, 110, 200, 44, 60, 70]  # sum = 506 ✓ (extra col)
            gap_rows = [[
                _cell("#", hdr_s), _cell("Regulation", hdr_s),
                _cell("Gap Description", hdr_s),
                _cell("Score", hdr_s), _cell("Range", hdr_s),
                _cell("Risk Level", hdr_s),
            ]]
            for i, gap in enumerate(scored_gaps, 1):
                lvl    = gap.get("risk_level", "")
                rcol   = RISK_COLORS.get(lvl, TEXT_DARK)
                rbg    = RISK_BG.get(lvl, WHITE)
                rs     = ParagraphStyle(f"R{i}", parent=cell_b, textColor=rcol)
                score_range = gap.get("score_range", "—")
                gap_rows.append([
                    _cell(str(i), cell_m),
                    _cell(gap.get("regulation", "N/A"), cell_s),
                    _cell(gap.get("gap", "N/A"), cell_s),
                    _cell(str(gap.get("severity", "N/A")), cell_b),
                    _cell(score_range, cell_m),
                    _cell(lvl, rs),
                ])
            gap_t = Table(gap_rows, colWidths=GAP_COLS, repeatRows=1)
            ts    = TableStyle(BASE_TS[:])
            for i, gap in enumerate(scored_gaps, 1):
                lvl = gap.get("risk_level", "")
                bg  = RISK_BG.get(lvl)
                if bg:
                    ts.add("BACKGROUND", (5, i), (5, i), bg)
            gap_t.setStyle(ts)
        else:
            GAP_COLS = [24, 125, 232, 46, 64]   # sum = 491 ✓ (original layout)
            gap_rows = [[
                _cell("#", hdr_s), _cell("Regulation", hdr_s),
                _cell("Gap Description", hdr_s),
                _cell("Score", hdr_s), _cell("Risk Level", hdr_s),
            ]]
            for i, gap in enumerate(scored_gaps, 1):
                lvl    = gap.get("risk_level", "")
                rcol   = RISK_COLORS.get(lvl, TEXT_DARK)
                rbg    = RISK_BG.get(lvl, WHITE)
                rs     = ParagraphStyle(f"R{i}", parent=cell_b, textColor=rcol)
                gap_rows.append([
                    _cell(str(i), cell_m),
                    _cell(gap.get("regulation", "N/A"), cell_s),
                    _cell(gap.get("gap", "N/A"), cell_s),
                    _cell(str(gap.get("severity", "N/A")), cell_b),
                    _cell(lvl, rs),
                ])
            gap_t = Table(gap_rows, colWidths=GAP_COLS, repeatRows=1)
            ts    = TableStyle(BASE_TS[:])
            for i, gap in enumerate(scored_gaps, 1):
                lvl = gap.get("risk_level", "")
                bg  = RISK_BG.get(lvl)
                if bg:
                    ts.add("BACKGROUND", (4, i), (4, i), bg)
            gap_t.setStyle(ts)

        story.append(gap_t)
    else:
        story.append(Paragraph(
            "No compliance gaps were identified. The company appears compliant "
            "with all applicable regulations.", styles["Body"]
        ))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════
    # REMEDIATION PLAN
    # ════════════════════════════════════════════════════════
    story.append(_section_header("Remediation Plan", styles))

    if remediations:
        REM_COLS = [24, 138, 218, 62, 72]   # sum = 514 ✓
        rem_rows = [[
            _cell("#", hdr_s), _cell("Gap", hdr_s),
            _cell("Recommended Action", hdr_s),
            _cell("Priority", hdr_s), _cell("Action Type", hdr_s),
        ]]
        for i, rem in enumerate(remediations, 1):
            pri     = rem.get("priority", "N/A")
            lbl     = rem.get("label", "N/A")
            pcol    = RISK_COLORS.get(pri.upper(), TEXT_DARK)
            ps      = ParagraphStyle(f"P{i}", parent=cell_b, textColor=pcol)
            lcol    = (colors.HexColor("#dc2626") if lbl == "mandatory"
                       else colors.HexColor("#2563eb"))
            ls      = ParagraphStyle(f"L{i}", parent=cell_s, textColor=lcol)
            rem_rows.append([
                _cell(str(i), cell_m),
                _cell(rem.get("gap", "N/A"), cell_s),
                _cell(rem.get("action", "N/A"), cell_s),
                _cell(pri.upper(), ps),
                _cell(lbl.replace("_", " ").title(), ls),
            ])

        rem_t = Table(rem_rows, colWidths=REM_COLS, repeatRows=1)
        rem_t.setStyle(TableStyle(BASE_TS))
        story.append(rem_t)
    else:
        story.append(Paragraph("No remediation actions required.", styles["Body"]))

    # ── Disclaimer ────────────────────────────────────────────
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Disclaimer:</b> This report is generated by an AI system and "
        "should be used as guidance only. It does not constitute legal advice. "
        "Please consult with qualified legal professionals for definitive "
        "compliance assessments.",
        ParagraphStyle("Disc", parent=styles["Normal"],
            fontSize=7.5, textColor=TEXT_LIGHT, alignment=TA_JUSTIFY)
    ))

    # ── External Research methodology note (footer) ───────────
    # A one-line methodology statement appended after the disclaimer
    # when analysis_mode is "external", as requested.
    if is_external:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "\u2b24 <b>Methodology Note:</b> This report was generated using "
            "external web research. Findings are tagged with confidence levels: "
            "CONFIRMED, PROBABLE, or UNKNOWN. Always verify PROBABLE and UNKNOWN "
            "findings against internal company documentation before remediation.",
            ParagraphStyle("ExtDisc", parent=styles["Normal"],
                fontSize=7.5, textColor=EXTERNAL_BADGE_BG, alignment=TA_JUSTIFY)
        ))

    # ── Build ─────────────────────────────────────────────────
    decorator = _make_page_decorator(company_name, generated_at, analysis_mode)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes