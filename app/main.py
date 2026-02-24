import os
import io
import json
import datetime as dt
from typing import Optional, Dict, List

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session
from sqlalchemy import or_, text, inspect

from .db import SessionLocal, engine, Base
from .models import ChecklistCategory, ChecklistItem, Visit, VisitChecklistLine, PartMemory
from .pdf_utils import build_jobcard_pdf
from .email_utils import send_email_with_pdf

# =========================
# CONFIG
# =========================
FIXED_RESET_CODE = os.getenv("RESET_CODE", "").strip() or "STE-2026"

COMPANY = {
    "name": "O&S STEPHANOU LTD",
    "lines": [
        "Michael Paridi 3, Palouriotissa",
        "Tel: 22436990-22436992",
        "Fax: 22437001",
        "Email: osstephanou@gmail.com",
        "Αρ. Μητρωου Φ.Π.Α: 10079915R",
        "Αρ.Φορ.Ταυτ.: 12079915T",
    ],
}

# =========================
# APP + STATIC
# =========================
app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # /.../app
STATIC_DIR = os.path.join(BASE_DIR, "static")           # /.../app/static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =========================
# DEBUG
# =========================
@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py", "static_dir": STATIC_DIR}

@app.get("/__staticcheck")
def __staticcheck():
    app_js = os.path.join(STATIC_DIR, "app.js")
    sw_js = os.path.join(STATIC_DIR, "sw.js")
    manifest = os.path.join(STATIC_DIR, "manifest.webmanifest")
    return JSONResponse({
        "static_dir": STATIC_DIR,
        "static_exists": os.path.isdir(STATIC_DIR),
        "app_js_exists": os.path.isfile(app_js),
        "sw_js_exists": os.path.isfile(sw_js),
        "manifest_exists": os.path.isfile(manifest),
        "static_files": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else []
    })

# =========================
# STARTUP
# =========================
DEFAULT_ITEMS = [
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Γενικο Σερβις"),
]

def _seed_checklist(db: Session):
    if db.query(ChecklistItem).count() > 0:
        return
    cats = set([c for c, _ in DEFAULT_ITEMS])
    for c in sorted(cats):
        db.add(ChecklistCategory(name=c))
    db.commit()
    for c, name in DEFAULT_ITEMS:
        db.add(ChecklistItem(category=c, name=name))
    db.commit()

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_checklist(db)
    finally:
        db.close()

# =========================
# UTIL
# =========================
def _model_key(v: Visit) -> str:
    return (v.model or "").strip().lower()

def _parse_dt(date_s: str, time_s: str) -> Optional[dt.datetime]:
    date_s = (date_s or "").strip()
    time_s = (time_s or "").strip()
    if not date_s:
        return None
    if not time_s:
        time_s = "00:00"
    try:
        y, m, d = [int(x) for x in date_s.split("-")]
        hh, mm = [int(x) for x in time_s.split(":")]
        return dt.datetime(y, m, d, hh, mm)
    except Exception:
        return None

def _selected_lines(lines: List[VisitChecklistLine]) -> List[VisitChecklistLine]:
    out = []
    for ln in lines:
        if ln.exclude_from_print:
            continue
        res = (ln.result or "").upper().strip()
        parts_code = (ln.parts_code or "").strip()
        notes = (ln.notes or "").strip()
        qty = int(ln.parts_qty or 0)
        if res in ("CHECK", "REPAIR") or qty > 0 or parts_code or notes:
            out.append(ln)
    return out

# =========================
# INDEX
# =========================
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), q: str = ""):
    visits_q = db.query(Visit)
    q = (q or "").strip()
    if q:
        visits_q = visits_q.filter(
            or_(
                Visit.customer_name.ilike(f"%{q}%"),
                Visit.plate_number.ilike(f"%{q}%"),
                Visit.phone.ilike(f"%{q}%"),
                Visit.email.ilike(f"%{q}%"),
                Visit.model.ilike(f"%{q}%"),
                Visit.vin.ilike(f"%{q}%"),
            )
        )
    visits = visits_q.order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "visits": visits, "q": q})

# =========================
# VISITS
# =========================
@app.post("/visits/new")
def visit_new(db: Session = Depends(get_db)):
    v = Visit()
    db.add(v)
    db.commit()
    db.refresh(v)

    items = db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()
    for it in items:
        db.add(
            VisitChecklistLine(
                visit_id=v.id,
                category=it.category,
                item_name=it.name,
                result="OK",
                notes="",
                parts_code="",
                parts_qty=0,
                exclude_from_print=False,
            )
        )
    db.commit()
    return RedirectResponse(f"/visits/{v.id}", status_code=302)

@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(visit_id: int, request: Request, db: Session = Depends(get_db), mode: str = "all"):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()

    mem = {}
    mk = _model_key(visit)
    if mk:
        rows = db.query(PartMemory).filter(PartMemory.model_key == mk).all()
        for r in rows:
            mem[(r.category, r.item_name)] = r.parts_code

    lines_to_show = _selected_lines(lines) if mode == "selected" else lines

    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": visit, "lines": lines_to_show, "all_lines": lines, "mode": mode, "mem": mem},
    )

@app.post("/visits/{visit_id}/save_all")
async def visit_save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = await request.form()

    visit.plate_number = (form.get("plate_number") or "").strip() or None
    visit.vin = (form.get("vin") or "").strip() or None
    visit.customer_name = (form.get("customer_name") or "").strip() or None
    visit.phone = (form.get("phone") or "").strip() or None
    visit.email = (form.get("email") or "").strip() or None
    visit.model = (form.get("model") or "").strip() or None
    visit.km = (form.get("km") or "").strip() or None
    visit.customer_complaint = (form.get("customer_complaint") or "").strip() or None

    di = _parse_dt(form.get("date_in") or "", form.get("time_in") or "")
    do = _parse_dt(form.get("date_out") or "", form.get("time_out") or "")
    if di:
        visit.date_in = di
    if do:
        visit.date_out = do

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    mk = _model_key(visit)

    for ln in lines:
        rid = str(ln.id)
        res = (form.get(f"result_{rid}") or "OK").strip().upper()
        if res not in ("OK", "CHECK", "REPAIR"):
            res = "OK"
        ln.result = res
        ln.notes = (form.get(f"notes_{rid}") or "").strip() or None
        ln.parts_code = (form.get(f"parts_code_{rid}") or "").strip() or None
        try:
            ln.parts_qty = int((form.get(f"parts_qty_{rid}") or "0").strip() or 0)
        except Exception:
            ln.parts_qty = 0
        ln.exclude_from_print = bool(form.get(f"exclude_{rid}") == "on")

        if mk and ln.parts_code:
            pm = db.query(PartMemory).filter(
                PartMemory.model_key == mk,
                PartMemory.category == (ln.category or ""),
                PartMemory.item_name == (ln.item_name or ""),
            ).first()
            if pm:
                pm.parts_code = ln.parts_code
            else:
                db.add(PartMemory(model_key=mk, category=ln.category or "", item_name=ln.item_name or "", parts_code=ln.parts_code or ""))

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)

@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
    return templates.TemplateResponse("print.html", {"request": request, "visit": visit, "lines": _selected_lines(lines), "company": COMPANY})

@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return JSONResponse({"error": "not found"}, status_code=404)
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
    pdf_bytes = build_jobcard_pdf(visit=visit, lines=_selected_lines(lines), company=COMPANY)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")

@app.post("/visits/{visit_id}/email")
def visit_email(visit_id: int, to_email: str = Form(...), db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
    pdf_bytes = build_jobcard_pdf(visit=visit, lines=_selected_lines(lines), company=COMPANY)
    ok, err = send_email_with_pdf(to_email=to_email, pdf_bytes=pdf_bytes, subject=f"Job Card #{visit.id}")
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=500)
    return {"ok": True}

# =========================
# CHECKLIST
# =========================
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    categories = db.query(ChecklistCategory).order_by(ChecklistCategory.name.asc()).all()
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    by_cat: Dict[str, List[ChecklistItem]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)
    return templates.TemplateResponse("checklist.html", {"request": request, "categories": categories, "by_cat": by_cat})

@app.post("/checklist/add")
def checklist_add(category: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    category = (category or "").strip()
    name = (name or "").strip()
    if not category or not name:
        return RedirectResponse("/checklist", status_code=302)

    cat = db.query(ChecklistCategory).filter(ChecklistCategory.name == category).first()
    if not cat:
        db.add(ChecklistCategory(name=category))
        db.commit()

    db.add(ChecklistItem(category=category, name=name))
    db.commit()
    return RedirectResponse("/checklist", status_code=302)

@app.post("/checklist/delete/{item_id}")
def checklist_delete(item_id: int, db: Session = Depends(get_db)):
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)

# =========================
# SEARCH
# =========================
@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, db: Session = Depends(get_db), q: str = ""):
    q = (q or "").strip()
    visits = []
    if q:
        visits = (
            db.query(Visit)
            .filter(
                or_(
                    Visit.customer_name.ilike(f"%{q}%"),
                    Visit.plate_number.ilike(f"%{q}%"),
                    Visit.phone.ilike(f"%{q}%"),
                    Visit.email.ilike(f"%{q}%"),
                    Visit.model.ilike(f"%{q}%"),
                    Visit.vin.ilike(f"%{q}%"),
                )
            )
            .order_by(Visit.id.desc())
            .limit(200)
            .all()
        )
    return templates.TemplateResponse("search.html", {"request": request, "visits": visits, "q": q})

# =========================
# HISTORY
# =========================
@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db), from_date: str = "", to_date: str = "", q: str = ""):
    q = (q or "").strip()
    visits_q = db.query(Visit)

    if from_date:
        try:
            d = dt.datetime.fromisoformat(from_date)
            visits_q = visits_q.filter(Visit.date_in >= d)
        except Exception:
            pass
    if to_date:
        try:
            d = dt.datetime.fromisoformat(to_date) + dt.timedelta(days=1)
            visits_q = visits_q.filter(Visit.date_in < d)
        except Exception:
            pass

    if q:
        visits_q = visits_q.filter(
            or_(
                Visit.customer_name.ilike(f"%{q}%"),
                Visit.plate_number.ilike(f"%{q}%"),
                Visit.phone.ilike(f"%{q}%"),
                Visit.email.ilike(f"%{q}%"),
                Visit.model.ilike(f"%{q}%"),
                Visit.vin.ilike(f"%{q}%"),
            )
        )

    visits = visits_q.order_by(Visit.id.desc()).limit(500).all()
    return templates.TemplateResponse("history.html", {"request": request, "visits": visits, "from_date": from_date, "to_date": to_date, "q": q})

# =========================
# BACKUP
# =========================
@app.get("/backup")
def backup_export(db: Session = Depends(get_db)):
    payload = {
        "version": 1,
        "exported_at": dt.datetime.utcnow().isoformat(),
        "checklist_items": [{"id": x.id, "category": x.category, "name": x.name} for x in db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()],
        "part_memories": [{"id": x.id, "model_key": x.model_key, "category": x.category, "item_name": x.item_name, "parts_code": x.parts_code} for x in db.query(PartMemory).order_by(PartMemory.id.asc()).all()],
        "visits": [{"id": v.id, "date_in": v.date_in.isoformat() if v.date_in else None, "date_out": v.date_out.isoformat() if v.date_out else None,
                    "plate_number": v.plate_number, "vin": v.vin, "model": v.model, "km": v.km,
                    "customer_name": v.customer_name, "phone": v.phone, "email": v.email, "customer_complaint": v.customer_complaint}
                   for v in db.query(Visit).order_by(Visit.id.asc()).all()],
        "visit_lines": [{"id": ln.id, "visit_id": ln.visit_id, "category": ln.category, "item_name": ln.item_name, "result": ln.result,
                         "notes": ln.notes, "parts_code": ln.parts_code, "parts_qty": ln.parts_qty, "exclude_from_print": ln.exclude_from_print}
                        for ln in db.query(VisitChecklistLine).order_by(VisitChecklistLine.id.asc()).all()],
    }
    b = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    fname = f"stefanou_backup_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.json"
    return StreamingResponse(io.BytesIO(b), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{fname}"'})

@app.post("/backup/import")
async def backup_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return RedirectResponse("/", status_code=302)

    # simple import (append)
    try:
        id_map = {}
        for v in data.get("visits", []):
            vv = Visit(
                plate_number=v.get("plate_number"),
                vin=v.get("vin"),
                model=v.get("model"),
                km=v.get("km"),
                customer_name=v.get("customer_name"),
                phone=v.get("phone"),
                email=v.get("email"),
                customer_complaint=v.get("customer_complaint"),
            )
            db.add(vv)
            db.flush()
            id_map[v.get("id")] = vv.id
        db.commit()

        for ln in data.get("visit_lines", []):
            db.add(
                VisitChecklistLine(
                    visit_id=id_map.get(ln.get("visit_id"), ln.get("visit_id")),
                    category=ln.get("category"),
                    item_name=ln.get("item_name"),
                    result=ln.get("result") or "OK",
                    notes=ln.get("notes"),
                    parts_code=ln.get("parts_code"),
                    parts_qty=int(ln.get("parts_qty") or 0),
                    exclude_from_print=bool(ln.get("exclude_from_print") or False),
                )
            )
        db.commit()
    except Exception:
        db.rollback()

    return RedirectResponse("/", status_code=302)

# =========================
# RESET
# =========================
@app.post("/reset")
async def reset_tests(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    code = (form.get("reset_password") or "").strip()
    if code != FIXED_RESET_CODE:
        return RedirectResponse("/?reset_error=1", status_code=302)

    try:
        driver = (engine.url.drivername or "").lower()
        visits_table = Visit.__table__.name
        lines_table = VisitChecklistLine.__table__.name

        if driver.startswith("postgresql"):
            db.execute(text(f'TRUNCATE TABLE "{lines_table}" RESTART IDENTITY CASCADE;'))
            db.execute(text(f'TRUNCATE TABLE "{visits_table}" RESTART IDENTITY CASCADE;'))
        else:
            db.query(VisitChecklistLine).delete(synchronize_session=False)
            db.query(Visit).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()

    return RedirectResponse("/", status_code=302)
