"""
PDF Generator Tool — Creates downloadable compliance report PDFs.

Used ONLY by the report_generator agent (Node 5) as the final step
of the analysis pipeline. Takes the structured report data and
generates a professional PDF document using ReportLab.

PDF Structure:
  Page 1:  Cover page with company name, date, risk score
  Page 2:  Executive summary
  Page 3+: Applicable regulations table
  Page N:  Gap analysis with severity colors
  Page N:  Remediation plan with priority labels
  Last:    Disclaimer and confidence notice

Color coding for risk levels:
  CRITICAL (80-100): Red    #FF4757
  HIGH     (60-79):  Orange #FF6B35
  MEDIUM   (40-59):  Yellow #FFA502
  LOW      (0-39):   Green  #2ED573

The generated PDF is returned as bytes (not saved to disk)
so it can be stored directly in PostgreSQL's reports table.
"""

import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY


# ── Risk Level Colors ────────────────────────────────────────
RISK_COLORS = {
    "CRITICAL": colors.HexColor("#FF4757"),
    "HIGH":     colors.HexColor("#FF6B35"),
    "MEDIUM":   colors.HexColor("#FFA502"),
    "LOW":      colors.HexColor("#2ED573"),
}

# ── Confidence Badge Colors ──────────────────────────────────
CONFIDENCE_COLORS = {
    "CONFIRMED": colors.HexColor("#2ED573"),   # green — verified
    "PROBABLE":  colors.HexColor("#FFA502"),    # yellow — inferred
    "UNKNOWN":   colors.HexColor("#FF4757"),    # red — unverifiable
}


def generate_pdf(report_data: dict) -> bytes:
    """
    Generate a compliance analysis PDF report.

    Args:
        report_data: Complete analysis data containing:
            - company_name: str
            - analysis_type: str
            - information_availability: str
            - overall_risk_score: int
            - overall_risk_level: str
            - risk_score_range: dict or None
            - confidence_level: str
            - applicable_regulations: list[dict]
            - scored_gaps: list[dict]
            - remediation_plan: list[dict]

    Returns:
        PDF file content as bytes.
        Stored directly in PostgreSQL reports.pdf_data column.
    """

    # Create an in-memory buffer — PDF bytes go here, not to disk
    buffer = io.BytesIO()

    # Build the PDF document with A4 page size
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=25 * mm,
        title=f"Compliance Report - {report_data.get('company_name', 'Unknown')}",
        author="AI Regulatory Compliance Agent"
    )

    # ── Custom Styles ────────────────────────────────────────
    styles = getSampleStyleSheet()

    # Title style for cover page
    styles.add(ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        fontSize=28,
        spaceAfter=20,
        textColor=colors.HexColor("#1a1a2e"),
        alignment=TA_CENTER
    ))

    # Section headers
    styles.add(ParagraphStyle(
        name="SectionHeader",
        parent=styles["Heading1"],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor("#16213e"),
        borderWidth=1,
        borderColor=colors.HexColor("#e2e8f0"),
        borderPadding=8
    ))

    # Body text with justified alignment
    styles.add(ParagraphStyle(
        name="BodyJustified",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=8
    ))

    # Risk score display style
    styles.add(ParagraphStyle(
        name="RiskScore",
        parent=styles["Title"],
        fontSize=48,
        alignment=TA_CENTER,
        spaceAfter=5
    ))

    # ── Build PDF Content ────────────────────────────────────
    story = []

    # Extract data with safe defaults
    company_name = report_data.get("company_name", "Unknown Company")
    analysis_type = report_data.get("analysis_type", "product")
    info_avail = report_data.get("information_availability", "full")
    risk_score = report_data.get("overall_risk_score", 0)
    risk_level = report_data.get("overall_risk_level", "LOW")
    risk_range = report_data.get("risk_score_range")
    confidence = report_data.get("confidence_level", "full")
    regulations = report_data.get("applicable_regulations", [])
    scored_gaps = report_data.get("scored_gaps", [])
    remediations = report_data.get("remediation_plan", [])

    # ── PAGE 1: Cover Page ───────────────────────────────────
    story.append(Spacer(1, 80))
    story.append(Paragraph("AI Regulatory Compliance", styles["CoverTitle"]))
    story.append(Paragraph("Gap Analysis Report", styles["CoverTitle"]))
    story.append(Spacer(1, 30))
    story.append(HRFlowable(
        width="80%", thickness=2,
        color=colors.HexColor("#3742fa"),
        spaceAfter=30
    ))

    # Company info table on cover
    cover_data = [
        ["Company:", company_name],
        ["Analysis Type:", analysis_type.title()],
        ["Information Level:", info_avail.title()],
        ["Date:", datetime.now().strftime("%B %d, %Y")],
        ["Confidence:", confidence.upper()],
    ]
    cover_table = Table(cover_data, colWidths=[120, 300])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(cover_table)

    # Risk score display
    story.append(Spacer(1, 40))
    risk_color = RISK_COLORS.get(risk_level, colors.gray)
    story.append(Paragraph(
        f'<font color="{risk_color.hexval()}">{risk_score}</font>',
        styles["RiskScore"]
    ))
    story.append(Paragraph(
        f'<font color="{risk_color.hexval()}">Risk Level: {risk_level}</font>',
        ParagraphStyle("RiskLabel", parent=styles["Normal"],
                       fontSize=14, alignment=TA_CENTER)
    ))

    # Show range for partial/minimal analyses
    if risk_range and confidence != "full":
        story.append(Paragraph(
            f'Score Range: {risk_range.get("min", "?")} - '
            f'{risk_range.get("max", "?")} '
            f'(Estimated: {risk_range.get("estimated", "?")})',
            ParagraphStyle("RangeLabel", parent=styles["Normal"],
                           fontSize=11, alignment=TA_CENTER,
                           textColor=colors.gray)
        ))

    story.append(PageBreak())

    # ── PAGE 2: Executive Summary ────────────────────────────
    story.append(Paragraph("Executive Summary", styles["SectionHeader"]))

    # Count gaps by severity
    critical_count = sum(1 for g in scored_gaps if g.get("risk_level") == "CRITICAL")
    high_count = sum(1 for g in scored_gaps if g.get("risk_level") == "HIGH")
    medium_count = sum(1 for g in scored_gaps if g.get("risk_level") == "MEDIUM")
    low_count = sum(1 for g in scored_gaps if g.get("risk_level") == "LOW")

    summary_text = (
        f"This report presents the regulatory compliance gap analysis for "
        f"<b>{company_name}</b>. The analysis was conducted in "
        f"<b>{analysis_type}</b> mode with <b>{info_avail}</b> information "
        f"availability. "
        f"A total of <b>{len(regulations)}</b> applicable regulations were "
        f"identified, with <b>{len(scored_gaps)}</b> compliance gaps found. "
        f"Of these gaps, <b>{critical_count}</b> are critical, "
        f"<b>{high_count}</b> are high severity, <b>{medium_count}</b> are "
        f"medium, and <b>{low_count}</b> are low severity."
    )
    story.append(Paragraph(summary_text, styles["BodyJustified"]))

    if confidence != "full":
        story.append(Spacer(1, 10))
        disclaimer = (
            f"<b>Note:</b> This analysis was conducted with {info_avail} "
            f"information availability. Some gaps are tagged as "
            f"{'PROBABLE' if info_avail == 'partial' else 'UNKNOWN'} "
            f"and should be verified with internal company documentation."
        )
        story.append(Paragraph(disclaimer, ParagraphStyle(
            "Disclaimer", parent=styles["Normal"],
            fontSize=10, textColor=colors.HexColor("#FF6B35"),
            borderWidth=1, borderColor=colors.HexColor("#FF6B35"),
            borderPadding=8
        )))

    story.append(Spacer(1, 15))

    # ── PAGE 3+: Applicable Regulations ──────────────────────
    story.append(Paragraph("Applicable Regulations", styles["SectionHeader"]))

    if regulations:
        reg_header = ["#", "Regulation", "Relevance", "Confidence"]
        reg_rows = [reg_header]
        for i, reg in enumerate(regulations, 1):
            reg_rows.append([
                str(i),
                reg.get("name", "N/A"),
                reg.get("relevance", "N/A")[:80],  # truncate long text
                reg.get("confidence", "N/A")
            ])

        reg_table = Table(reg_rows, colWidths=[30, 150, 230, 80])
        reg_table.setStyle(TableStyle([
            # Header row styling
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            # Body styling
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(reg_table)
    else:
        story.append(Paragraph(
            "No applicable regulations were identified.",
            styles["BodyJustified"]
        ))

    story.append(PageBreak())

    # ── Gap Analysis ─────────────────────────────────────────
    story.append(Paragraph("Compliance Gaps", styles["SectionHeader"]))

    if scored_gaps:
        gap_header = ["#", "Regulation", "Gap", "Severity", "Risk"]
        gap_rows = [gap_header]
        for i, gap in enumerate(scored_gaps, 1):
            gap_rows.append([
                str(i),
                gap.get("regulation", "N/A"),
                gap.get("gap", "N/A")[:100],
                str(gap.get("severity", "N/A")),
                gap.get("risk_level", "N/A")
            ])

        gap_table = Table(gap_rows, colWidths=[25, 100, 240, 50, 60])
        gap_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))

        # Color-code the risk level column based on severity
        for i, gap in enumerate(scored_gaps, 1):
            level = gap.get("risk_level", "")
            if level in RISK_COLORS:
                gap_table.setStyle(TableStyle([
                    ("TEXTCOLOR", (4, i), (4, i), RISK_COLORS[level]),
                    ("FONTNAME", (4, i), (4, i), "Helvetica-Bold"),
                ]))

        story.append(gap_table)
    else:
        story.append(Paragraph(
            "No compliance gaps were identified. The company appears "
            "to be compliant with all applicable regulations.",
            styles["BodyJustified"]
        ))

    story.append(PageBreak())

    # ── Remediation Plan ─────────────────────────────────────
    story.append(Paragraph("Remediation Plan", styles["SectionHeader"]))

    if remediations:
        rem_header = ["#", "Gap", "Recommended Action", "Priority", "Label"]
        rem_rows = [rem_header]
        for i, rem in enumerate(remediations, 1):
            rem_rows.append([
                str(i),
                rem.get("gap", "N/A")[:80],
                rem.get("action", "N/A")[:120],
                rem.get("priority", "N/A"),
                rem.get("label", "N/A")
            ])

        rem_table = Table(rem_rows, colWidths=[25, 120, 200, 60, 70])
        rem_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(rem_table)
    else:
        story.append(Paragraph(
            "No remediation actions required.",
            styles["BodyJustified"]
        ))

    # ── Final Disclaimer ─────────────────────────────────────
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6")))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<b>Disclaimer:</b> This report is generated by an AI system and "
        "should be used as guidance only. It does not constitute legal advice. "
        "Please consult with qualified legal professionals for definitive "
        "compliance assessments.",
        ParagraphStyle("FinalDisclaimer", parent=styles["Normal"],
                       fontSize=8, textColor=colors.gray, alignment=TA_JUSTIFY)
    ))

    # ── Build the PDF ────────────────────────────────────────
    doc.build(story)

    # Return PDF bytes from the in-memory buffer
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
