import io
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics


def build_jobcard_pdf(company: dict, visit: dict, lines: list[dict]) -> bytes:
    """
    Returns PDF bytes for a job card.
    Uses Arial TTF located at: app/assets/arial.ttf (uploaded by you)
    """

    # Register font (Greek-friendly)
    font_path = os.path.join(os.path.dirname(__file__), "assets", "arial.ttf")
    pdfmetrics.registerFont(TTFont("ArialUnicode", font_path))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Helper
    def t(x, y, text, size=10):
        c.setFont("ArialUnicode", size)
        c.drawString(x, y, text if text is not None else "")

    y = h - 40

    # Header
    t(40, y, company.get("name", "O&S STEPHANOU LTD"), 14); y -= 18
    for line in company.get("lines", []):
        t(40, y, line, 10); y -= 14
    y -= 8

    # Visit / Customer
    t(40, y, f"JOB: {visit.get('job_no','')}", 12); y -= 18
    t(40, y, f"Plate: {visit.get('plate_number','')}    VIN: {visit.get('vin','')}"); y -= 14
    t(40, y, f"Model: {visit.get('model','')}    KM: {visit.get('km','')}"); y -= 14
    t(40, y, f"Customer: {visit.get('customer_name','')}"); y -= 14
    t(40, y, f"Phone: {visit.get('phone','')}    Email: {visit.get('email','')}"); y -= 14
    complaint = visit.get("customer_complaint", "")
    if complaint:
        t(40, y, f"Complaint: {complaint}"); y -= 14

    y -= 12
    t(40, y, "Checklist", 12); y -= 16

    # Table headers
    t(40, y, "Category", 10)
    t(170, y, "Item", 10)
    t(360, y, "Result", 10)
    t(440, y, "Parts code", 10)
    t(520, y, "Qty", 10)
    y -= 12
    c.line(40, y, w - 40, y)
    y -= 14

    # Lines
    for ln in lines:
        if y < 60:
            c.showPage()
            y = h - 40

        t(40, y, str(ln.get("category", ""))[:18], 9)
        t(170, y, str(ln.get("item_name", ""))[:30], 9)
        t(360, y, str(ln.get("result", ""))[:12], 9)
        t(440, y, str(ln.get("parts_code", ""))[:16], 9)
        t(520, y, str(ln.get("parts_qty", "")), 9)
        y -= 12

    c.showPage()
    c.save()

    return buf.getvalue()
