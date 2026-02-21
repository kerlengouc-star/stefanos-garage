from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import os
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from datetime import datetime
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import os

def build_jobcard_pdf(company: dict, visit: dict, lines: list[dict]) -> bytes:font_path = os.path.join(os.path.dirname(__file__), "assets", "arial.ttf")
pdfmetrics.registerFont(TTFont("ArialUnicode", font_path))
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    y = height - 18 * mm

    # Header
    c.setFont("Helvetica-Bold", 12)
    c.drawString(18*mm, y, company.get("name",""))
    y -= 6*mm
    c.setFont("Helvetica", 9)
    c.drawString(18*mm, y, company.get("address","") or "")
    y -= 5*mm
    c.drawString(18*mm, y, f"Tel: {company.get('tel','') or ''}   Fax: {company.get('fax','') or ''}")
    y -= 5*mm
    c.drawString(18*mm, y, f"Email: {company.get('email','') or ''}")
    y -= 5*mm
    c.drawString(18*mm, y, f"VAT: {company.get('vat','') or ''}   Tax ID: {company.get('tax_id','') or ''}")

    y -= 10*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18*mm, y, f"JOB CARD: {visit.get('job_no','')}")
    y -= 6*mm

    c.setFont("Helvetica", 9)
    c.drawString(18*mm, y, f"Ημ/νία: {visit.get('date_in','')}")
    y -= 5*mm
    c.drawString(18*mm, y, f"Αρ. Εγγραφής: {visit.get('plate_number','') or ''}    VIN: {visit.get('vin','') or ''}")
    y -= 5*mm
    c.drawString(18*mm, y, f"Όνομα: {visit.get('customer_name','') or ''}    Τηλ: {visit.get('phone','') or ''}")
    y -= 5*mm
    c.drawString(18*mm, y, f"Email: {visit.get('email','') or ''}    Μοντέλο: {visit.get('model','') or ''}    KM: {visit.get('km','') or ''}")

    y -= 7*mm
    complaint = (visit.get("customer_complaint") or "").strip()
    if complaint:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(18*mm, y, "Παράπονο/Αίτημα πελάτη:")
        y -= 5*mm
        c.setFont("Helvetica", 9)
        c.drawString(18*mm, y, complaint[:1100])
        y -= 7*mm

    # Table header
    c.setFont("Helvetica-Bold", 9)
    c.drawString(18*mm, y, "Σημείο")
    c.drawString(95*mm, y, "Αποτέλεσμα")
    c.drawString(130*mm, y, "Parts")
    c.drawString(150*mm, y, "Labor")
    c.drawString(170*mm, y, "Total")
    y -= 4*mm
    c.line(18*mm, y, 195*mm, y)
    y -= 6*mm

    c.setFont("Helvetica", 8)
    for ln in lines:
        if y < 20*mm:
            c.showPage()
            y = height - 18*mm
            c.setFont("Helvetica", 8)

        item = ln.get("item_name","")
        res = ln.get("result","")
        parts = f"{ln.get('parts_cost',0):.2f}"
        labor = f"{ln.get('labor_cost',0):.2f}"
        total = f"{ln.get('line_total',0):.2f}"

        c.drawString(18*mm, y, item[:45])
        c.drawString(95*mm, y, res)
        c.drawRightString(145*mm, y, parts)
        c.drawRightString(165*mm, y, labor)
        c.drawRightString(195*mm, y, total)
        y -= 5*mm

    y -= 6*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(195*mm, y, f"Σύνολο: {visit.get('total_amount',0):.2f} €")

    c.setFont("Helvetica", 7)
    c.drawString(18*mm, 10*mm, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    c.save()
    return buf.getvalue()
