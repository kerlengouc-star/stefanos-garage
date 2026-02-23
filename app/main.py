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

# =========================
# DEFAULT CHECKLIST SEED ✅
# =========================
DEFAULT_CATEGORY = "ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ"

DEFAULT_ITEMS = [
    "Γενικό Σέρβις",
    "Στοπερ μπροστά",
    "Στοπερ πίσω",
    "Φλάντζες μπροστά",
    "Φλάντζες πίσω",
    "Χειρόφρενο",
    "Λάδι μηχανής",
    "Λάδι gearbox",
    "Clutch",
    "Oilcooler",
    "Starter",
    "Δυναμός",
    "Αξονάκια",
    "Αέριο A/C",
    "Θερμοκρασία",
    "Καθαριστήρες",
    "Λάμπες",
    "Κολάνι",
    "Κόντρα σούστες μπροστά",
    "Κόντρα σούστες πίσω",
    "Λάστιχα",
    "Γύρισμα ελαστικών",
    "Μπαταρία",
    "Μπίτε καθαριστήρων",
    "Κόντρα σούστες καπό μπροστά",
    "Κόντρα σούστες καπό πίσω",
]

def seed_checklist_if_empty(db: Session):
    """Βάζει τις default κατηγορίες ΜΟΝΟ αν δεν υπάρχει τίποτα στη βάση."""
    try:
        cnt = db.query(ChecklistItem).count()
    except Exception:
        cnt = 0

    if cnt and cnt > 0:
        return

    for name in DEFAULT_ITEMS:
        db.add(ChecklistItem(category=DEFAULT_CATEGORY, name=name))
    db.commit()

@app.on_event("startup")
def on_startup():
    # Δημιουργία πινάκων (fix "no such table")
    Base.metadata.create_all(bind=engine)

    # Seed κατηγοριών αν η βάση είναι άδεια ✅
    db = SessionLocal()
    try:
        seed_checklist_if_empty(db)
    finally:
        db.close()

# =========================
# AUTH (dummy – δεν σπάει)
# =========================
HAS_USER = False

def require_user(request: Request, db: Session) -> Optional[Any]:
    return {"ok": True}

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
        "checklist_count": db.query(ChecklistItem).count(),
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

# ✅ FIX: δέχεται ΚΑΙ GET ΚΑΙ POST
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
# SAVE ALL
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

    field_map = {
        "job_no": "job_no",
        "plate_number": "plate_number",
        "vin": "vin",
        "customer_name": "customer_name",
        "phone": "phone",
        "email": "email",
        "model": "model",
        "km": "km",
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

    # Προσθήκη νέας εργασίας χωρίς να χάνεται τίποτα
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
# RESET TEST
# =========================
@app.api_route("/reset-test", methods=["GET", "POST"])
async def reset_test(request: Request, db: Session = Depends(get_db)):
    FIXED_RESET_CODE = "STE-2026"

    code = ""
    if request.method == "POST":
        form = await request.form()
        code = (form.get("code") or "").strip()
    else:
        code = (request.query_params.get("code") or "").strip()

    if code != FIXED_RESET_CODE:
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
            "remaining_visits": db.query(Visit).count(),
            "remaining_lines": db.query(VisitChecklistLine).count(),
            "checklist_count": db.query(ChecklistItem).count(),
        }

    except Exception as e:
        db.rollback()
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)
