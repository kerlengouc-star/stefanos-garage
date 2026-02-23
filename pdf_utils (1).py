import os
import io
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def _try_register_font():
    """
    ✅ Fix Greek + symbols reliably on Render/Linux
    Tries DejaVuSans; falls back to Helvetica if not found.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", p))
                return "DejaVuSans"
            except Exception:
                pass
    return "Helvetica"


FONT = _try_register_font()


def _fmt_dt(dt):
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


def build_jobcard_pdf(company: dict, visit: dict, lines: list[dict]) -> bytes:
    """
    ✅ NO Paragraph/HTML parsing (so O&S never becomes O;S)
    ✅ Includes dates/times
    ✅ Includes only selected lines (caller already filters)
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setTitle("Job Card")

    # margins
    x = 40
    y = h - 50

    c.setFont(FONT, 14)
    c.drawString(x, y, company.get("name", ""))
    y -= 18

    c.setFont(FONT, 9)
    for ln in company.get("lines", []):
        c.drawString(x, y, ln)
        y -= 12

    y -= 10
    c.setLineWidth(0.8)
    c.line(x, y, w - x, y)
    y -= 20

    c.setFont(FONT, 12)
    c.drawString(x, y, f"JOB: {visit.get('job_no', '')}")
    y -= 18

    c.setFont(FONT, 10)
    c.drawString(x, y, f"Αρ. Εγγραφής: {visit.get('plate_number','')}")
    c.drawString(x + 260, y, f"VIN: {visit.get('vin','')}")
    y -= 14
    c.drawString(x, y, f"Μοντέλο: {visit.get('model','')}")
    c.drawString(x + 260, y, f"KM: {visit.get('km','')}")
    y -= 14
    c.drawString(x, y, f"Όνομα: {visit.get('customer_name','')}")
    y -= 14
    c.drawString(x, y, f"Τηλέφωνο: {visit.get('phone','')}")
    c.drawString(x + 260, y, f"Email: {visit.get('email','')}")
    y -= 14

    # ✅ Dates/times
    c.drawString(x, y, f"Ημ/νία & Ώρα Άφιξης: {_fmt_dt(visit.get('date_in'))}")
    y -= 14
    c.drawString(x, y, f"Ημ/νία & Ώρα Παράδοσης: {_fmt_dt(visit.get('date_out'))}")
    y -= 18

    complaint = (visit.get("customer_complaint") or "").strip()
    if complaint:
        c.setFont(FONT, 10)
        c.drawString(x, y, "Απαίτηση / Σχόλια πελάτη:")
        y -= 14
        c.setFont(FONT, 9)
        # wrap basic
        max_chars = 95
        for i in range(0, len(complaint), max_chars):
            c.drawString(x, y, complaint[i : i + max_chars])
            y -= 12
        y -= 8

    c.setFont(FONT, 11)
    c.drawString(x, y, "ΕΠΙΛΕΓΜΕΝΕΣ ΕΡΓΑΣΙΕΣ (CHECK / REPAIR / PARTS)")
    y -= 10
    c.line(x, y, w - x, y)
    y -= 16

    # table header
    c.setFont(FONT, 9)
    c.drawString(x, y, "Κατηγορία / Εργασία")
    c.drawString(x + 305, y, "Status")
    c.drawString(x + 365, y, "Parts No")
    c.drawString(x + 470, y, "Qty")
    y -= 12
    c.line(x, y, w - x, y)
    y -= 14

    c.setFont(FONT, 9)

    last_cat = None
    for ln in lines:
        cat = (ln.get("category") or "").strip()
        item = (ln.get("item_name") or "").strip()
        status = (ln.get("result") or "").strip()
        parts_code = (ln.get("parts_code") or "").strip()
        qty = str(ln.get("parts_qty") or 0)

        if y < 70:
            c.showPage()
            c.setFont(FONT, 9)
            y = h - 60

        if cat and cat != last_cat:
            c.setFont(FONT, 10)
            c.drawString(x, y, cat)
            y -= 12
            c.setFont(FONT, 9)
            last_cat = cat

        text = f"• {item}"
        c.drawString(x, y, text[:48])
        c.drawString(x + 305, y, status)
        c.drawString(x + 365, y, parts_code[:18])
        c.drawString(x + 470, y, qty)
        y -= 12

        notes = (ln.get("notes") or "").strip()
        if notes:
            c.setFont(FONT, 8)
            c.drawString(x + 18, y, f"Σημείωση: {notes[:90]}")
            c.setFont(FONT, 9)
            y -= 12

    c.setFont(FONT, 8)
    c.drawString(x, 40, f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    c.save()
    return buf.getvalue()
