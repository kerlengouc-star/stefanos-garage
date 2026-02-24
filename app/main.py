import os
import io
import json
import datetime as dt
from typing import Optional, Dict, Tuple, List

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    StreamingResponse,
    JSONResponse,
)
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from sqlalchemy import or_, text, inspect

from .db import SessionLocal, engine, Base
from .models import ChecklistCategory, ChecklistItem, Visit, VisitChecklistLine, PartMemory
from .pdf_utils import build_jobcard_pdf
from .email_utils import send_email_with_pdf

# =========================
# CONFIG
# =========================
FIXED_RESET_CODE = os.getenv("RESET_CODE", "").strip() or "STE-2026"  # μπορείς να το αλλάξεις εδώ

COMPANY = {
    "name": "O&S STEPHANOU LTD",
    "lines": [
        "Michael Paridi 3, Palouriotissa",
        "Tel: 22436990-22436936992",
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

# Serve static files (PWA: app.js, sw.js, manifest)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# =========================
# DB schema safety (auto-migrate μικρές αλλαγές)
# =========================
def _ensure_schema():
    """Προσθέτει columns που λείπουν (χωρίς Alembic), ώστε να μην σκάει το app μετά από update."""
    try:
        with engine.begin() as conn:
            url = str(engine.url)
            if url.startswith("sqlite"):
                # SQLite: έλεγχος columns με PRAGMA
                cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(visits)").fetchall()]
                if "notes_general" not in cols:
                    conn.exec_driver_sql("ALTER TABLE visits ADD COLUMN notes_general TEXT")
            else:
                # Postgres/MySQL: δοκίμασε IF NOT EXISTS (Postgres OK). Αν αποτύχει, το αγνοούμε.
                try:
                    conn.exec_driver_sql("ALTER TABLE visits ADD COLUMN IF NOT EXISTS notes_general TEXT")
                except Exception:
                    # fallback: αν ήδη υπάρχει ή DB δεν το υποστηρίζει
                    pass
    except Exception as e:
        # Δεν σταματάμε το startup – απλά θα φανεί στα logs.
        print("Schema ensure warning:", repr(e))

@app.on_event("startup")
def _startup_migrate():
    _ensure_schema()



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
    # seed categories + items
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


def _visit_dict(v: Visit) -> dict:
    return {
        "id": v.id,
        "plate_number": v.plate_number or "",
        "vin": v.vin or "",
        "model": v.model or "",
        "km": v.km or "",
        "customer_name": v.customer_name or "",
        "phone": v.phone or "",
        "email": v.email or "",
        "customer_complaint": v.customer_complaint or "",
        "date_in": v.date_in,
        "date_out": v.date_out,
        "notes_general": getattr(v, "notes_general", None),
    }


def _line_dict(ln: VisitChecklistLine) -> dict:
    return {
        "category": ln.category or "",
        "item_name": ln.item_name or "",
        "result": ln.result or "",
        "notes": ln.notes or "",
        "parts_code": ln.parts_code or "",
        "parts_qty": int(ln.parts_qty or 0),
        "exclude_from_print": bool(ln.exclude_from_print or False),
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
    insp = inspect(engine)
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

    # create lines for all checklist items (stable editing + printing)
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

    # part memories for autofill (per model+category+item)
    mem = {}
    mk = _model_key(visit)
    if mk:
        rows = db.query(PartMemory).filter(PartMemory.model_key == mk).all()
        for r in rows:
            mem[(r.category, r.item_name)] = r.parts_code

    if mode == "selected":
        lines_to_show = _selected_lines(lines)
    else:
        lines_to_show = lines

    return templates.TemplateResponse(
        "visit.html",
        {
            "request": request,
            "visit": visit,
            "lines": lines_to_show,
            "all_lines": lines,
            "mode": mode,
            "mem": mem,
        },
    )


@app.post("/visits/{visit_id}/save_all")
async def visit_save_all(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = await request.form()

    # update visit fields
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

    # arrival / delivery (from browser inputs)
    di = _parse_dt(form.get("date_in") or "", form.get("time_in") or "")
    do = _parse_dt(form.get("date_out") or "", form.get("time_out") or "")
    if di:
        visit.date_in = di
    if do:
        visit.date_out = do

    # update each line
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

        # save memory for autofill (per model key)
        if mk and ln.parts_code:
            pm = db.query(PartMemory).filter(
                PartMemory.model_key == mk,
                PartMemory.category == (ln.category or ""),
                PartMemory.item_name == (ln.item_name or ""),
            ).first()
            if pm:
                pm.parts_code = ln.parts_code
            else:
                db.add(
                    PartMemory(
                        model_key=mk,
                        category=ln.category or "",
                        item_name=ln.item_name or "",
                        parts_code=ln.parts_code or "",
                    )
                )

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

    lines_to_show = _selected_lines(lines)

    return templates.TemplateResponse(
        "print.html",
        {"request": request, "visit": visit, "lines": lines_to_show, "company": COMPANY},
    )


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
def visit_email(
    visit_id: int,
    to_email: str = Form(...),
    db: Session = Depends(get_db),
):
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
# CHECKLIST ADMIN
# =========================
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    categories = db.query(ChecklistCategory).order_by(ChecklistCategory.name.asc()).all()
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    by_cat: Dict[str, List[ChecklistItem]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)
    return templates.TemplateResponse(
        "checklist.html",
        {"request": request, "categories": categories, "by_cat": by_cat},
    )


@app.post("/checklist/add")
def checklist_add(category: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    category = (category or "").strip()
    name = (name or "").strip()
    if not category or not name:
        return RedirectResponse("/checklist", status_code=302)

    # ensure category exists
    cat = db.query(ChecklistCategory).filter(ChecklistCategory.name == category).first()
    if not cat:
        db.add(ChecklistCategory(name=category))
        db.commit()

    # create item
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
def history_page(
    request: Request,
    db: Session = Depends(get_db),
    from_date: str = "",
    to_date: str = "",
    q: str = "",
):
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

    return templates.TemplateResponse(
        "history.html",
        {"request": request, "visits": visits, "from_date": from_date, "to_date": to_date, "q": q},
    )


# =========================
# BACKUP EXPORT / IMPORT
# =========================
@app.get("/backup")
def backup_export(db: Session = Depends(get_db)):
    data = {
        "visits": [_visit_dict(v) for v in db.query(Visit).order_by(Visit.id.asc()).all()],
        "visit_lines": [_line_dict(ln) for ln in db.query(VisitChecklistLine).order_by(VisitChecklistLine.id.asc()).all()],
        "checklist_categories": [{"id": c.id, "name": c.name} for c in db.query(ChecklistCategory).order_by(ChecklistCategory.id.asc()).all()],
        "checklist_items": [{"id": i.id, "category": i.category, "name": i.name} for i in db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()],
        "part_memories": [{"id": p.id, "model_key": p.model_key, "category": p.category, "item_name": p.item_name, "parts_code": p.parts_code} for p in db.query(PartMemory).order_by(PartMemory.id.asc()).all()],
    }
    return JSONResponse(data)


@app.post("/backup/import")
async def backup_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    data = json.loads(content.decode("utf-8"))

    # very simple import: append / map ids
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
            if hasattr(vv, "notes_general"):
                setattr(vv, "notes_general", v.get("notes_general"))
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
# RESET (tests) – με κωδικό
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
