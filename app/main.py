import os
import io
import json
import datetime as dt
from typing import Optional, Any, List, Tuple

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    StreamingResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm import Session
from sqlalchemy import inspect, or_, text
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from .db import SessionLocal, engine, Base
from .models import ChecklistItem, Visit, VisitChecklistLine

# =========================
# APP
# =========================
app = FastAPI()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="app/templates")

# =========================
# DB
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def on_startup():
    # Δημιουργία πινάκων (fix "no such table")
    Base.metadata.create_all(bind=engine)

# =========================
# AUTH (κρατάμε dummy – δεν σπάει τίποτα)
# =========================
HAS_USER = False

def require_user(request: Request, db: Session) -> Optional[Any]:
    return {"ok": True}  # dummy user

# =========================
# HEALTH / DEBUG
# =========================
@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py"}

@app.get("/__dbinfo")
def __dbinfo(db: Session = Depends(get_db)):
    return {
        "driver": getattr(engine.url, "drivername", "unknown"),
        "database_url": str(engine.url),
        "visits_count": db.query(Visit).count(),
    }

@app.get("/__tables")
def __tables(db: Session = Depends(get_db)):
    insp = inspect(engine)
    tables = insp.get_table_names()
    out = {"tables": []}
    for t in tables:
        try:
            cnt = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        except Exception as e:
            cnt = f"error: {e}"
        out["tables"].append({"table": t, "count": cnt})
    return out

# =========================
# INDEX / VISITS
# =========================
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": u, "visits": visits})

# ✅ FIX: δέχεται ΚΑΙ GET ΚΑΙ POST (για να μην βγάζει Method Not Allowed)
@app.api_route("/visits/new", methods=["GET", "POST"])
def visit_new(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)

    now = dt.datetime.now()
    v = Visit()

    # Αυτόματα ημερομηνία/ώρα παραλαβής (ώρα υπολογιστή)
    if hasattr(v, "date_in"):
        setattr(v, "date_in", now.date().isoformat())
    if hasattr(v, "time_in"):
        setattr(v, "time_in", now.strftime("%H:%M"))

    # default status
    if hasattr(v, "status") and not getattr(v, "status", None):
        setattr(v, "status", "open")

    db.add(v)
    db.commit()
    db.refresh(v)
    return RedirectResponse(f"/visits/{v.id}", status_code=302)

@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {
        ln.checklist_item_id: ln
        for ln in lines
        if getattr(ln, "checklist_item_id", None) is not None
    }

    return templates.TemplateResponse(
        "visit.html",
        {
            "request": request,
            "user": u,
            "visit": visit,
            "items": items,
            "line_by_item": line_by_item,
            "now_date": dt.date.today().isoformat(),
            "now_time": dt.datetime.now().strftime("%H:%M"),
        },
    )

# =========================
# SAVE ALL (ένα Save μόνο)
# =========================
@app.api_route("/visits/{visit_id}/save_all", methods=["POST"])
async def visit_save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = dict(await request.form())

    def set_if(field: str, val: Any):
        if hasattr(visit, field):
            setattr(visit, field, val)

    # βασικά πεδία (ασφαλές: μόνο αν υπάρχουν)
    field_map = {
        "job_no": "job_no",
        "plate_number": "plate_number",
        "vin": "vin",
        "customer_name": "customer_name",
        "phone": "phone",
        "email": "email",
        "model": "model",
        "km": "km",
        # στο UI το λέμε "Απαίτηση πελάτη", αλλά κρατάμε ίδιο db field
        "customer_complaint": "customer_complaint",
        "notes_general": "notes_general",
        "date_in": "date_in",
        "time_in": "time_in",
        "date_out": "date_out",
        "time_out": "time_out",
        "total_parts": "total_parts",
        "total_labor": "total_labor",
        "total_amount": "total_amount",
        "status": "status",
    }

    for k, mf in field_map.items():
        if k in form:
            set_if(mf, (form.get(k) or "").strip())

    # αν λείπει ημερομηνία/ώρα παραλαβής, βάλε από υπολογιστή
    now = dt.datetime.now()
    if hasattr(visit, "date_in") and not (getattr(visit, "date_in", "") or "").strip():
        set_if("date_in", now.date().isoformat())
    if hasattr(visit, "time_in") and not (getattr(visit, "time_in", "") or "").strip():
        set_if("time_in", now.strftime("%H:%M"))

    # προσθήκη νέας κατηγορίας/εργασίας χωρίς να σβήνει τις επιλογές
    new_category = (form.get("new_category") or "").strip()
    new_item_name = (form.get("new_item_name") or "").strip()
    if new_category and new_item_name:
        exists = (
            db.query(ChecklistItem)
            .filter(ChecklistItem.category == new_category, ChecklistItem.name == new_item_name)
            .first()
        )
        if not exists:
            db.add(ChecklistItem(category=new_category, name=new_item_name))
            db.commit()

    # αποθήκευση γραμμών checklist
    items = db.query(ChecklistItem).all()
    existing_lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {
        ln.checklist_item_id: ln
        for ln in existing_lines
        if getattr(ln, "checklist_item_id", None) is not None
    }

    for it in items:
        cid = it.id
        checked = form.get(f"chk_{cid}") in ("on", "1", "true", "True")
        notes = (form.get(f"notes_{cid}") or "").strip()
        parts_code = (form.get(f"parts_code_{cid}") or "").strip()
        parts_qty = (form.get(f"parts_qty_{cid}") or "").strip()

        ln = line_by_item.get(cid)
        if not ln:
            ln = VisitChecklistLine(visit_id=visit_id, checklist_item_id=cid)
            db.add(ln)

        if hasattr(ln, "checked"):
            ln.checked = bool(checked)
        if hasattr(ln, "notes"):
            ln.notes = notes
        if hasattr(ln, "parts_code"):
            ln.parts_code = parts_code
        if hasattr(ln, "parts_qty"):
            ln.parts_qty = parts_qty

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)

# =========================
# CHECKLIST ADMIN
# =========================
@app.get("/checklist", response_class=HTMLResponse)
def checklist_page(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "user": u, "items": items})

@app.post("/checklist/add")
def checklist_add(
    request: Request,
    db: Session = Depends(get_db),
    category: str = Form(...),
    name: str = Form(...),
):
    u = require_user(request, db)
    category = category.strip()
    name = name.strip()
    if category and name:
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
            db.add(ChecklistItem(category=category, name=name))
            db.commit()
    return RedirectResponse("/checklist", status_code=302)

@app.post("/checklist/delete/{item_id}")
def checklist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)

# =========================
# SEARCH
# =========================
@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    u = require_user(request, db)
    q = (q or "").strip()
    results = []
    if q:
        results = (
            db.query(Visit)
            .filter(
                or_(
                    Visit.customer_name.ilike(f"%{q}%"),
                    Visit.plate_number.ilike(f"%{q}%"),
                    Visit.phone.ilike(f"%{q}%"),
                    Visit.email.ilike(f"%{q}%"),
                    Visit.model.ilike(f"%{q}%"),
                    Visit.job_no.ilike(f"%{q}%"),
                )
            )
            .order_by(Visit.id.desc())
            .limit(200)
            .all()
        )
    return templates.TemplateResponse("search.html", {"request": request, "user": u, "q": q, "results": results})

# =========================
# HISTORY
# =========================
@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, from_date: str = "", to_date: str = "", db: Session = Depends(get_db)):
    u = require_user(request, db)
    q = db.query(Visit)
    if from_date and hasattr(Visit, "date_in"):
        q = q.filter(Visit.date_in >= from_date)
    if to_date and hasattr(Visit, "date_in"):
        q = q.filter(Visit.date_in <= to_date)
    visits = q.order_by(Visit.id.desc()).limit(500).all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "user": u, "from_date": from_date, "to_date": to_date, "visits": visits},
    )

# =========================
# PRINT + PDF (μόνο επιλεγμένα/συμπληρωμένα)
# =========================
def _selected_lines(db: Session, visit_id: int) -> List[Tuple[ChecklistItem, VisitChecklistLine]]:
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {
        ln.checklist_item_id: ln
        for ln in lines
        if getattr(ln, "checklist_item_id", None) is not None
    }

    selected: List[Tuple[ChecklistItem, VisitChecklistLine]] = []
    for it in items:
        ln = line_by_item.get(it.id)
        if not ln:
            continue
        checked = bool(getattr(ln, "checked", False))
        notes = (getattr(ln, "notes", "") or "").strip()
        pcode = (getattr(ln, "parts_code", "") or "").strip()
        pqty = (getattr(ln, "parts_qty", "") or "").strip()
        if checked or notes or pcode or pqty:
            selected.append((it, ln))
    return selected

@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)
    selected = _selected_lines(db, visit_id)
    return templates.TemplateResponse("print.html", {"request": request, "user": u, "visit": visit, "selected": selected})

def _pdf_bytes_for_visit(visit: Visit, selected: List[Tuple[ChecklistItem, VisitChecklistLine]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 40

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "O&S STEPHANOU LTD")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(40, y, "Michael Paridi 3, Palouriotissa | Tel: 22436990-22436992 | Email: osstephanou@gmail.com")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "JOB CARD")
    y -= 18
    c.setFont("Helvetica", 10)

    def line(label: str, value: Any):
        nonlocal y
        value = "" if value is None else str(value)
        c.drawString(40, y, f"{label}: {value}")
        y -= 14

    line("Job No", getattr(visit, "job_no", ""))
    line("Ημ/νία Παραλαβής", getattr(visit, "date_in", ""))
    line("Ώρα Παραλαβής", getattr(visit, "time_in", ""))
    line("Ημ/νία Παράδοσης", getattr(visit, "date_out", ""))
    line("Ώρα Παράδοσης", getattr(visit, "time_out", ""))
    y -= 6
    line("Πελάτης", getattr(visit, "customer_name", ""))
    line("Τηλέφωνο", getattr(visit, "phone", ""))
    line("Email", getattr(visit, "email", ""))
    line("Αρ. Πινακίδας", getattr(visit, "plate_number", ""))
    line("VIN", getattr(visit, "vin", ""))
    line("Μοντέλο", getattr(visit, "model", ""))
    line("KM", getattr(visit, "km", ""))

    y -= 8
    req_txt = getattr(visit, "customer_complaint", "")
    if req_txt:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, "Απαίτηση πελάτη:")
        y -= 14
        c.setFont("Helvetica", 10)
        c.drawString(40, y, str(req_txt)[:160])
        y -= 16

    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Επιλεγμένες Εργασίες")
    y -= 16
    c.setFont("Helvetica", 10)

    for it, ln in selected:
        checked = bool(getattr(ln, "checked", False))
        notes = (getattr(ln, "notes", "") or "").strip()
        pcode = (getattr(ln, "parts_code", "") or "").strip()
        pqty = (getattr(ln, "parts_qty", "") or "").strip()

        parts_txt = ""
        if pcode or pqty:
            parts_txt = f" | Κωδικός εξαρτήματος: {pcode} | Ποσότητα: {pqty}"
        notes_txt = f" | Σημειώσεις: {notes}" if notes else ""
        ok_txt = " | OK" if checked else ""

        txt = f"- [{it.category}] {it.name}{ok_txt}{parts_txt}{notes_txt}"

        if y < 60:
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 10)

        c.drawString(40, y, txt[:180])
        y -= 14

    c.showPage()
    c.save()
    return buf.getvalue()

@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)
    selected = _selected_lines(db, visit_id)
    pdf_bytes = _pdf_bytes_for_visit(visit, selected)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="visit_{visit_id}.pdf"'},
    )

# =========================
# EMAIL (δίνουμε .eml)
# =========================
@app.get("/visits/{visit_id}/email")
def visit_email_eml(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    to_addr = (getattr(visit, "email", "") or "").strip()
    subject = f"Job Card #{getattr(visit, 'job_no', visit_id)}"
    body = "Καλησπέρα,\n\nΣας επισυνάπτουμε την κάρτα εργασίας.\n\nΜε εκτίμηση,\nO&S STEPHANOU LTD\n"
    eml = (
        f"To: {to_addr}\n"
        f"Subject: {subject}\n"
        f"Content-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n"
        f"PDF: {request.base_url}visits/{visit_id}/pdf\n"
    )
    return PlainTextResponse(eml, headers={"Content-Disposition": f'attachment; filename="visit_{visit_id}.eml"'})

# =========================
# BACKUP / IMPORT
# =========================
@app.get("/backup")
def backup_download(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)

    items = db.query(ChecklistItem).all()
    visits = db.query(Visit).all()
    lines = db.query(VisitChecklistLine).all()

    payload = {
        "version": 1,
        "exported_at": dt.datetime.utcnow().isoformat() + "Z",
        "checklist_items": [{"id": it.id, "category": it.category, "name": it.name} for it in items],
        "visits": [{c.name: getattr(v, c.name) for c in v.__table__.columns} for v in visits],
        "visit_lines": [{c.name: getattr(ln, c.name) for c in ln.__table__.columns} for ln in lines],
    }

    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="backup.json"'},
    )

@app.post("/import-backup")
async def import_backup(request: Request, db: Session = Depends(get_db), file: UploadFile = File(...)):
    u = require_user(request, db)

    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON backup"}, status_code=400)

    # checklist items (χωρίς duplicates)
    for it in payload.get("checklist_items", []):
        category = (it.get("category") or "").strip()
        name = (it.get("name") or "").strip()
        if not category or not name:
            continue
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
            db.add(ChecklistItem(category=category, name=name))
    db.commit()

    # visits
    for v in payload.get("visits", []):
        obj = Visit()
        for k, val in v.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    # lines
    for ln in payload.get("visit_lines", []):
        obj = VisitChecklistLine()
        for k, val in ln.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    return RedirectResponse("/", status_code=302)

# =========================
# RESET TEST (δέχεται ΚΑΙ GET ΚΑΙ POST για να μην "κολλάει")
# =========================
@app.api_route("/reset-test", methods=["GET", "POST"])
async def reset_test(request: Request, db: Session = Depends(get_db)):
    """
    Σβήνει ΟΛΟ το ιστορικό:
    - VisitChecklistLine
    - Visit
    Δεν πειράζει τις κατηγορίες (ChecklistItem).
    Κωδικός μέσα στον κώδικα.
    """

    FIXED_RESET_CODE = "STE-2026"

    code = ""
    if request.method == "POST":
        form = await request.form()
        code = (form.get("code") or "").strip()
    else:
        code = (request.query_params.get("code") or "").strip()

    if code != FIXED_RESET_CODE:
        # Επιστρέφουμε ξεκάθαρα λάθος κωδικό (ώστε να ξέρεις ότι δουλεύει)
        return JSONResponse({"ok": False, "error": "Wrong code"}, status_code=403)

    try:
        driver = (engine.url.drivername or "").lower()
        visits_table = Visit.__table__.name
        lines_table = VisitChecklistLine.__table__.name

        if driver.startswith("postgresql"):
            db.execute(text(f'TRUNCATE TABLE "{lines_table}" RESTART IDENTITY CASCADE;'))
            db.execute(text(f'TRUNCATE TABLE "{visits_table}" RESTART IDENTITY CASCADE;'))
            db.commit()
        else:
            db.query(VisitChecklistLine).delete(synchronize_session=False)
            db.query(Visit).delete(synchronize_session=False)
            db.commit()

        return {
            "ok": True,
            "message": "Reset completed",
            "driver": driver,
            "remaining_visits": db.query(Visit).count(),
            "remaining_lines": db.query(VisitChecklistLine).count(),
        }

    except Exception as e:
        db.rollback()
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)
