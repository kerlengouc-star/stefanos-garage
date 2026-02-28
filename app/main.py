import os
import io
import json
import datetime as dt
from typing import Optional, Dict, List

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    StreamingResponse,
    JSONResponse,
    FileResponse,
)
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from sqlalchemy import or_, text, inspect as sa_inspect

from .db import SessionLocal, engine, Base
from .models import ChecklistItem, Visit, VisitChecklistLine, PartMemory
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
# APP
# =========================
app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory="app/templates")


# Serve SW at root scope
@app.get("/sw.js")
def sw_root():
    return FileResponse(
        os.path.join(STATIC_DIR, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# =========================
# DB
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DEFAULT_ITEMS = [
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Γενικο Σερβις"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Στοπερ μπροστα"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Στοπερ πισω"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Φλαντζες μπροστα"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Φλαντζες πισω"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Χειροφρενο"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Λαδι μηχανης"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Λαδι gearbox"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Clutch"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Oilcouller"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Starter"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Δυναμος"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Αξονακια"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Αεριο A/C"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Θερμοκρασια"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Καθαριστηρες"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Λαμπες"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Κολανι"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Κοντρα σουστες μπροστα"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Κοντρα σουστες πισω"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Λαστιχα"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Γυρισμα ελαστικων"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Μπαταρια"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Μπιτε καθαριστηρων"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Κοντρα σουστες καπο μπροστα"),
    ("ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ", "Κοντρα σουστες καπο πισω"),
]


def _seed_checklist(db: Session):
    if db.query(ChecklistItem).count() > 0:
        return
    for cat, name in DEFAULT_ITEMS:
        db.add(ChecklistItem(category=cat, name=name))
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


def _visit_dict(v: Visit) -> dict:
    return {
        "id": v.id,
        "job_no": v.job_no or "",
        "plate_number": v.plate_number or "",
        "vin": v.vin or "",
        "model": v.model or "",
        "km": v.km or "",
        "customer_name": v.customer_name or "",
        "phone": v.phone or "",
        "email": v.email or "",
        "customer_complaint": v.customer_complaint or "",
        "notes_general": getattr(v, "notes_general", "") or "",
        "date_in": v.date_in,
        "date_out": v.date_out,
    }


def _line_dict(ln: VisitChecklistLine) -> dict:
    return {
        "category": ln.category or "",
        "item_name": ln.item_name or "",
        "result": ln.result or "",
        "notes": ln.notes or "",
        "parts_code": ln.parts_code or "",
        "parts_qty": int(ln.parts_qty or 0),
    }


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
        "part_memories_count": db.query(PartMemory).count(),
        "lines_count": db.query(VisitChecklistLine).count(),
    }


@app.get("/__tables")
def __tables(db: Session = Depends(get_db)):
    insp = sa_inspect(engine)
    tables = insp.get_table_names()
    out = {"tables": []}
    for t in tables:
        try:
            cnt = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        except Exception:
            try:
                cnt = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            except Exception as e:
                cnt = f"error: {e}"
        out["tables"].append({"table": t, "count": cnt})
    return out


@app.get("/__staticcheck")
def __staticcheck():
    app_js = os.path.join(STATIC_DIR, "app.js")
    sw_js = os.path.join(STATIC_DIR, "sw.js")
    manifest = os.path.join(STATIC_DIR, "manifest.webmanifest")
    return {
        "static_dir": STATIC_DIR,
        "static_exists": os.path.isdir(STATIC_DIR),
        "app_js_exists": os.path.isfile(app_js),
        "sw_js_exists": os.path.isfile(sw_js),
        "manifest_exists": os.path.isfile(manifest),
        "static_files": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else [],
    }


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
                Visit.job_no.ilike(f"%{q}%"),
            )
        )
    visits = visits_q.order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "visits": visits, "q": q})


# =========================
# VISITS
# =========================
@app.get("/visits/new", response_class=HTMLResponse)
def visit_new_page(request: Request):
    return templates.TemplateResponse("visit.html", {"request": request, "visit": None})


# ✅ ΒΗΜΑ 4: ΠΑΝΤΑ date_in = ΤΩΡΑ
@app.post("/visits/new")
def visit_new(
    customer_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    plate_number: str = Form(""),
    model: str = Form(""),
    vin: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    now = dt.datetime.now()

    v = Visit(
        customer_name=(customer_name or "").strip() or None,
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        plate_number=(plate_number or "").strip() or None,
        model=(model or "").strip() or None,
        vin=(vin or "").strip() or None,
        date_in=now,  # ✅ εδώ
    )
    if hasattr(v, "notes_general"):
        v.notes_general = (notes or "").strip() or None

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


@app.post("/visits/{visit_id}/add_line")
def visit_add_line(
    visit_id: int,
    new_category: str = Form(""),
    new_item: str = Form(""),
    make_permanent: str = Form(""),
    db: Session = Depends(get_db),
):
    new_category = (new_category or "").strip()
    new_item = (new_item or "").strip()
    is_permanent = (make_permanent == "on")

    if not new_category or not new_item:
        return RedirectResponse(f"/visits/{visit_id}", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    if is_permanent:
        exists = (
            db.query(ChecklistItem)
            .filter(ChecklistItem.category == new_category, ChecklistItem.name == new_item)
            .first()
        )
        if not exists:
            db.add(ChecklistItem(category=new_category, name=new_item))
            db.commit()

    line_exists = (
        db.query(VisitChecklistLine)
        .filter(
            VisitChecklistLine.visit_id == visit_id,
            VisitChecklistLine.category == new_category,
            VisitChecklistLine.item_name == new_item,
        )
        .first()
    )
    if not line_exists:
        db.add(
            VisitChecklistLine(
                visit_id=visit_id,
                category=new_category,
                item_name=new_item,
                result="OK",
                notes="",
                parts_code="",
                parts_qty=0,
                exclude_from_print=False,
            )
        )
        db.commit()

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(visit_id: int, request: Request, db: Session = Depends(get_db), mode: str = "all"):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    all_lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )

    mem = {}
    mk = _model_key(visit)
    if mk:
        rows = db.query(PartMemory).filter(PartMemory.model_key == mk).all()
        for r in rows:
            mem[(r.category, r.item_name)] = r.parts_code

    lines_to_show = _selected_lines(all_lines) if mode == "selected" else all_lines

    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": visit, "lines": lines_to_show, "all_lines": all_lines, "mode": mode, "mem": mem},
    )


@app.post("/visits/{visit_id}/save_all")
async def visit_save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = await request.form()
    mode = (form.get("mode") or "all").strip()

    visit.plate_number = (form.get("plate_number") or "").strip() or None
    visit.vin = (form.get("vin") or "").strip() or None
    visit.customer_name = (form.get("customer_name") or "").strip() or None
    visit.phone = (form.get("phone") or "").strip() or None
    visit.email = (form.get("email") or "").strip() or None
    visit.model = (form.get("model") or "").strip() or None
    visit.km = (form.get("km") or "").strip() or None
    visit.customer_complaint = (form.get("customer_complaint") or "").strip() or None
    if hasattr(visit, "notes_general"):
        visit.notes_general = (form.get("notes_general") or "").strip() or None

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

        ln.notes = (form.get(f"notes_{rid}") or "").strip()
        ln.parts_code = (form.get(f"parts_code_{rid}") or "").strip()

        try:
            ln.parts_qty = int((form.get(f"parts_qty_{rid}") or "0").strip() or 0)
        except Exception:
            ln.parts_qty = 0

        ln.exclude_from_print = (form.get(f"exclude_{rid}") == "on")

        if mk and ln.parts_code:
            existing = (
                db.query(PartMemory)
                .filter(
                    PartMemory.model_key == mk,
                    PartMemory.category == (ln.category or ""),
                    PartMemory.item_name == (ln.item_name or ""),
                )
                .first()
            )
            if existing:
                existing.parts_code = ln.parts_code
                existing.updated_at = dt.datetime.utcnow()
            else:
                db.add(
                    PartMemory(
                        model_key=mk,
                        category=(ln.category or ""),
                        item_name=(ln.item_name or ""),
                        parts_code=ln.parts_code,
                    )
                )

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}?mode={mode}&saved=1", status_code=302)


# =========================
# PDF / PRINT / EMAIL
# =========================
@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )
    selected = _selected_lines(lines)

    pdf_bytes = build_jobcard_pdf(COMPANY, _visit_dict(visit), [_line_dict(x) for x in selected])
    filename = f"jobcard_{visit_id}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{filename}"'
    })


@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )
    selected = _selected_lines(lines)
    return templates.TemplateResponse("print.html", {"request": request, "visit": visit, "lines": selected})


@app.post("/visits/{visit_id}/email")
def visit_email(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    to_email = (visit.email or "").strip()
    if not to_email:
        return RedirectResponse(f"/visits/{visit_id}?mode=all", status_code=302)

    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )
    selected = _selected_lines(lines)
    pdf_bytes = build_jobcard_pdf(COMPANY, _visit_dict(visit), [_line_dict(x) for x in selected])

    subject = f"Job Card {visit.job_no or visit.id}"
    body = "Σας επισυνάπτουμε το Job Card σε PDF.\n\nO&S STEPHANOU LTD"
    try:
        send_email_with_pdf(to_email, subject, body, pdf_bytes, filename=f"jobcard_{visit.id}.pdf")
    except Exception:
        return RedirectResponse(f"/visits/{visit_id}?mode=all&email_error=1", status_code=302)

    return RedirectResponse(f"/visits/{visit_id}?mode=all&email_sent=1", status_code=302)


# =========================
# CHECKLIST ADMIN
# =========================
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "items": items})


@app.post("/checklist/add")
def checklist_add(db: Session = Depends(get_db), category: str = Form(...), name: str = Form(...)):
    category = category.strip()
    name = name.strip()
    if category and name:
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
            db.add(ChecklistItem(category=category, name=name))
            db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/edit/{item_id}")
def checklist_edit(item_id: int, db: Session = Depends(get_db), category: str = Form(...), name: str = Form(...)):
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        it.category = (category or "").strip()
        it.name = (name or "").strip()
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
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
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
                    Visit.vin.ilike(f"%{q}%"),
                    Visit.job_no.ilike(f"%{q}%"),
                )
            )
            .order_by(Visit.id.desc())
            .limit(200)
            .all()
        )
    return templates.TemplateResponse("search.html", {"request": request, "q": q, "results": results})


# =========================
# HISTORY
# =========================
@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db), from_date: str = "", to_date: str = "", q: str = ""):
    q = (q or "").strip()
    qy = db.query(Visit)

    def _d(s: str) -> Optional[dt.datetime]:
        s = (s or "").strip()
        if not s:
            return None
        try:
            y, m, d = [int(x) for x in s.split("-")]
            return dt.datetime(y, m, d, 0, 0)
        except Exception:
            return None

    d1 = _d(from_date)
    d2 = _d(to_date)
    if d1:
        qy = qy.filter(Visit.date_in >= d1)
    if d2:
        qy = qy.filter(Visit.date_in < (d2 + dt.timedelta(days=1)))

    if q:
        qy = qy.filter(
            or_(
                Visit.customer_name.ilike(f"%{q}%"),
                Visit.plate_number.ilike(f"%{q}%"),
                Visit.phone.ilike(f"%{q}%"),
                Visit.email.ilike(f"%{q}%"),
                Visit.model.ilike(f"%{q}%"),
                Visit.vin.ilike(f"%{q}%"),
                Visit.job_no.ilike(f"%{q}%"),
            )
        )

    visits = qy.order_by(Visit.id.desc()).limit(500).all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "visits": visits, "from_date": from_date, "to_date": to_date, "q": q},
    )


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
