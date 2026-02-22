import os
from datetime import datetime
from typing import Dict, List, Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle


def _try_register_unicode_font() -> str:
    """
    Fix for Render: don't rely on app/assets/arial.ttf.
    Try common Linux font paths (DejaVu Sans). If not found, fall back to Helvetica.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", p))
                return "DejaVuSans"
            except Exception:
                pass
    return "Helvetica"


def build_jobcard_pdf(company: Dict[str, Any], visit: Dict[str, Any], lines: List[Dict[str, Any]]) -> bytes:
    font_name = _try_register_unicode_font()

    # Styles
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "base",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=12,
        alignment=TA_LEFT,
    )
    h1 = ParagraphStyle(
        "h1",
        parent=base,
        fontSize=14,
        leading=16,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=base,
        fontSize=11,
        leading=13,
        spaceBefore=6,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "small",
        parent=base,
        fontSize=9,
        leading=11,
    )

    # Build PDF in memory
    from io import BytesIO
    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Job Card",
    )

    story = []

    # Header company
    story.append(Paragraph(company.get("name", "Garage"), h1))
    comp_lines = company.get("lines") or []
    for ln in comp_lines:
        story.append(Paragraph(str(ln), small))
    story.append(Spacer(1, 6))

    # Visit info
    job_no = visit.get("job_no", "")
    story.append(Paragraph(f"JOB CARD: {job_no}", h2))

    def fmt_dt(x):
        if not x:
            return ""
        # if it's datetime already
        if isinstance(x, datetime):
            return x.strftime("%Y-%m-%d %H:%M")
        return str(x)

    info_rows = [
        ["Αρ. Εγγραφής", visit.get("plate_number", ""), "Αρ. Πλαισίου", visit.get("vin", "")],
        ["Μοντέλο", visit.get("model", ""), "KM/H", visit.get("km", "")],
        ["Όνομα", visit.get("customer_name", ""), "Τηλέφωνο", visit.get("phone", "")],
        ["Email", visit.get("email", ""), " ", " "],
        ["Άφιξη", fmt_dt(visit.get("date_in", "")), "Παράδοση", fmt_dt(visit.get("date_out", ""))],
    ]

    t_info = Table(info_rows, colWidths=[28 * mm, 62 * mm, 28 * mm, 62 * mm])
    t_info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_info)

    complaint = (visit.get("customer_complaint") or "").strip()
    if complaint:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Παράπονο / Σχόλια πελάτη:", h2))
        story.append(Paragraph(complaint.replace("\n", "<br/>"), base))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Checklist", h2))

    # Group lines by category
    grouped = {}
    for ln in lines:
        cat = (ln.get("category") or "").strip() or "Χωρίς Κατηγορία"
        grouped.setdefault(cat, []).append(ln)

    # Table per category
    for cat, items in grouped.items():
        story.append(Paragraph(cat, h2))

        table_data = [["Έλεγχος", "Κατάσταση", "Parts Number", "Ποσότητα"]]
        for it in items:
            table_data.append([
                it.get("item_name", ""),
                it.get("result", ""),
                it.get("parts_code", ""),
                str(it.get("parts_qty", "") if it.get("parts_qty", "") is not None else ""),
            ])

        t = Table(table_data, colWidths=[78 * mm, 24 * mm, 52 * mm, 22 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 6))

    doc.build(story)
    return buf.getvalue()
