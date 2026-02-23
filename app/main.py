import os
import io
import json
import datetime as dt
from typing import Optional, Dict, Tuple, List

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
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
                Visit.vin.ilike(f"%{q}%"),            )
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

        ln.notes = (form.get(f"notes_{rid}") or "").strip()

        ln.parts_code = (form.get(f"parts_code_{rid}") or "").strip()
        try:
            ln.parts_qty = int((form.get(f"parts_qty_{rid}") or "0").strip() or 0)
        except Exception:
            ln.parts_qty = 0

        ln.exclude_from_print = (form.get(f"exclude_{rid}") == "on")

        # upsert part memory if we have model + parts_code
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
    # If called via fetch/AJAX, don't redirect (keeps page state manageable)
    accept = (request.headers.get("accept") or "").lower()
    xrw = (request.headers.get("x-requested-with") or "").lower()
    if "application/json" in accept or xrw == "xmlhttprequest":
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/visits/{visit_id}?mode=all", status_code=302)



@app.post("/visits/{visit_id}/add_item")
async def visit_add_item(visit_id: int, request: Request, db: Session = Depends(get_db)):
    """Add (category + item) to global checklist and to the current visit, without overwriting visit fields."""
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = await request.form()
    new_cat = (form.get("new_category") or "").strip()
    new_item = (form.get("new_item") or "").strip()
    if new_cat and new_item:
        # ensure exists in master list
        exists = (
            db.query(ChecklistItem)
            .filter(ChecklistItem.category == new_cat, ChecklistItem.name == new_item)
            .first()
        )
        if not exists:
            db.add(ChecklistItem(category=new_cat, name=new_item))
            db.commit()

        # ensure line not already in this visit
        line_exists = (
            db.query(VisitChecklistLine)
            .filter(
                VisitChecklistLine.visit_id == visit_id,
                VisitChecklistLine.category == new_cat,
                VisitChecklistLine.item_name == new_item,
            )
            .first()
        )
        if not line_exists:
            db.add(
                VisitChecklistLine(
                    visit_id=visit.id,
                    category=new_cat,
                    item_name=new_item,
                    result="OK",
                    notes="",
                    parts_code="",
                    parts_qty=0,
                    exclude_from_print=False,
                )
            )
            db.commit()

    # If called via fetch/AJAX, don't redirect
    accept = (request.headers.get("accept") or "").lower()
    xrw = (request.headers.get("x-requested-with") or "").lower()
    if "application/json" in accept or xrw == "xmlhttprequest":
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/visits/{visit_id}?mode=all", status_code=302)


@app.post("/visits/{visit_id}/delete_line/{line_id}")
def visit_delete_line(visit_id: int, line_id: int, db: Session = Depends(get_db)):
    ln = db.query(VisitChecklistLine).filter(VisitChecklistLine.id == line_id, VisitChecklistLine.visit_id == visit_id).first()
    if ln:
        db.delete(ln)
        db.commit()
    return RedirectResponse(f"/visits/{visit_id}?mode=all", status_code=302)


@app.post("/visits/{visit_id}/delete_category")
async def visit_delete_category(visit_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat = (form.get("category") or "").strip()
    if cat:
        db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id, VisitChecklistLine.category == cat).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse(f"/visits/{visit_id}?mode=all", status_code=302)



# =========================
# PDF / PRINT / EMAIL
# =========================
@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
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
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
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

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).order_by(
        VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc()
    ).all()
    selected = _selected_lines(lines)
    pdf_bytes = build_jobcard_pdf(COMPANY, _visit_dict(visit), [_line_dict(x) for x in selected])

    subject = f"Job Card {visit.id}"
    body = "Σας επισυνάπτουμε το Job Card σε PDF.\n\nO&S STEPHANOU LTD"
    try:
        send_email_with_pdf(to_email, subject, body, pdf_bytes, filename=f"jobcard_{visit.id}.pdf")
    except Exception as e:
        # δείξε error απλά στο UI ως query param (για να μην σπάει)
        return RedirectResponse(f"/visits/{visit_id}?mode=all&email_error=1", status_code=302)

    return RedirectResponse(f"/visits/{visit_id}?mode=all&email_sent=1", status_code=302)


# =========================
# CHECKLIST ADMIN
# =========================
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "items": items})



def _ensure_category(db: Session, name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    exists = db.query(ChecklistCategory).filter(ChecklistCategory.name == name).first()
    if not exists:
        db.add(ChecklistCategory(name=name))
        db.commit()


@app.post("/categories/add")
async def categories_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return RedirectResponse(url="/", status_code=302)
    _ensure_category(db, name)
    # επιστρέφει πίσω από όπου ήρθε (π.χ. /visits/ID ή /checklist)
    back = request.headers.get("referer") or "/"
    return RedirectResponse(url=back, status_code=302)

@app.post("/checklist/add")
def checklist_add(
    db: Session = Depends(get_db),
    category: str = Form(...),
    name: str = Form(...),
):
    category = category.strip()
    name = name.strip()
    if category and name:
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
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


@app.post("/checklist/edit/{item_id}")
async def checklist_edit(item_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    category = (form.get("category") or "").strip()
    name = (form.get("name") or "").strip()
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it and category and name:
        it.category = category
        it.name = name
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
                    Visit.vin.ilike(f"%{q}%"),                )
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
def history_page(
    request: Request,
    db: Session = Depends(get_db),
    from_date: str = "",
    to_date: str = "",
    q: str = "",
):
    q = (q or "").strip()
    qy = db.query(Visit)

    # date range uses Visit.date_in
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
                Visit.vin.ilike(f"%{q}%"),            )
        )

    visits = qy.order_by(Visit.id.desc()).limit(500).all()

    visit_ids = [v.id for v in visits]
    summaries: Dict[int, str] = {}
    if visit_ids:
        # Load related checklist lines in one query
        lines = (
            db.query(VisitChecklistLine)
            .filter(VisitChecklistLine.visit_id.in_(visit_ids))
            .order_by(VisitChecklistLine.visit_id.asc(), VisitChecklistLine.id.asc())
            .all()
        )
        by_visit: Dict[int, List[VisitChecklistLine]] = {}
        for ln in lines:
            by_visit.setdefault(ln.visit_id, []).append(ln)

        for v in visits:
            parts: List[str] = []
            if v.customer_complaint:
                parts.append(f"Παράπονο: {v.customer_complaint}")
            if v.notes_general:
                parts.append(f"Σημ.: {v.notes_general}")

            # include only non-OK lines or lines with notes/parts
            extra = []
            for ln in by_visit.get(v.id, []):
                if (ln.result and ln.result != "OK") or (ln.notes and ln.notes.strip()) or (ln.parts_code and ln.parts_code.strip()):
                    label = f"{ln.category}: {ln.item_name}"
                    if ln.result and ln.result != "OK":
                        label += f" [{ln.result}]"
                    if ln.notes and ln.notes.strip():
                        label += f" — {ln.notes.strip()}"
                    if ln.parts_code and ln.parts_code.strip():
                        qty = ln.parts_qty or 0
                        label += f" (Parts: {ln.parts_code}{' x'+str(qty) if qty else ''})"
                    extra.append(label)

            if extra:
                parts.append(" / ".join(extra[:4]) + (f" (+{len(extra)-4})" if len(extra) > 4 else ""))

            summaries[v.id] = " | ".join([p.strip() for p in parts if p.strip()])


    return templates.TemplateResponse(
        "history.html",
        {"request": request, "visits": visits, "summaries": summaries, "from_date": from_date, "to_date": to_date, "q": q},
    )


# =========================
# BACKUP / IMPORT
# =========================
@app.get("/backup")
def backup_export(db: Session = Depends(get_db)):
    payload = {
        "version": 1,
        "exported_at": dt.datetime.utcnow().isoformat(),
        "checklist_items": [
            {"id": x.id, "category": x.category, "name": x.name}
            for x in db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()
        ],
        "part_memories": [
            {
                "id": x.id,
                "model_key": x.model_key,
                "category": x.category,
                "item_name": x.item_name,
                "parts_code": x.parts_code,
                "updated_at": x.updated_at.isoformat() if x.updated_at else None,
            }
            for x in db.query(PartMemory).order_by(PartMemory.id.asc()).all()
        ],
        "visits": [
            {
                "id": v.id,                "date_in": v.date_in.isoformat() if v.date_in else None,
                "date_out": v.date_out.isoformat() if v.date_out else None,
                "plate_number": v.plate_number,
                "vin": v.vin,
                "model": v.model,
                "km": v.km,
                "customer_name": v.customer_name,
                "phone": v.phone,
                "email": v.email,
                "customer_complaint": v.customer_complaint,
                "notes_general": getattr(v, "notes_general", None),
            }
            for v in db.query(Visit).order_by(Visit.id.asc()).all()
        ],
        "visit_lines": [
            {
                "id": ln.id,
                "visit_id": ln.visit_id,
                "category": ln.category,
                "item_name": ln.item_name,
                "result": ln.result,
                "notes": ln.notes,
                "parts_code": ln.parts_code,
                "parts_qty": ln.parts_qty,
                "exclude_from_print": ln.exclude_from_print,
            }
            for ln in db.query(VisitChecklistLine).order_by(VisitChecklistLine.id.asc()).all()
        ],
    }

    b = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    fname = f"stefanou_backup_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.json"
    return StreamingResponse(io.BytesIO(b), media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{fname}"'
    })


@app.post("/backup/import")
async def backup_import(request: Request, db: Session = Depends(get_db), file: UploadFile = File(...)):
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return RedirectResponse("/", status_code=302)

    # replace everything (safe for restore)
    try:
        driver = (engine.url.drivername or "").lower()
        tables = [
            VisitChecklistLine.__table__.name,
            Visit.__table__.name,
            PartMemory.__table__.name,
            ChecklistItem.__table__.name,
        ]
        if driver.startswith("postgresql"):
            for t in tables:
                db.execute(text(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE;'))
        else:
            db.query(VisitChecklistLine).delete(synchronize_session=False)
            db.query(Visit).delete(synchronize_session=False)
            db.query(PartMemory).delete(synchronize_session=False)
            db.query(ChecklistItem).delete(synchronize_session=False)
        db.commit()

        for it in data.get("checklist_items", []):
            db.add(ChecklistItem(category=it.get("category") or "", name=it.get("name") or ""))

        db.commit()

        for pm in data.get("part_memories", []):
            db.add(
                PartMemory(
                    model_key=pm.get("model_key") or "",
                    category=pm.get("category") or "",
                    item_name=pm.get("item_name") or "",
                    parts_code=pm.get("parts_code") or "",
                    updated_at=dt.datetime.fromisoformat(pm["updated_at"]) if pm.get("updated_at") else dt.datetime.utcnow(),
                )
            )
        db.commit()

        id_map = {}
        for v in data.get("visits", []):
            vv = Visit(                date_in=dt.datetime.fromisoformat(v["date_in"]) if v.get("date_in") else None,
                date_out=dt.datetime.fromisoformat(v["date_out"]) if v.get("date_out") else None,
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
