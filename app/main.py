import os
import traceback
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from sqlalchemy import or_, text

from .db import get_db, engine
from .models import Base, ChecklistItem, Visit, VisitChecklistLine
from .pdf_utils import build_jobcard_pdf

app = FastAPI()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DEFAULT_CATEGORY = "ΒΑΣΙΚΑ ΣΤΟΙΧΕΙΑ ΟΧΗΜΑΤΟΣ"
DEFAULT_CHECKLIST = [
    "Γενικο Σερβις",
    "Στοπερ μπροστα",
    "Στοπερ πισω",
    "Φλαντζες μπροστα",
    "Φλαντζες πισω",
    "Χειροφρενο",
    "Λαδι μηχανης",
    "Λαδι gearbox",
    "Clutch",
    "Oilcouller",
    "Starter",
    "Δυναμος",
    "Αξονακια",
    "Αεριο A/C",
    "Θερμοκρασια",
    "Καθαριστηρες",
    "Λαμπες",
    "Κολανι",
    "Κοντρα σουστες μπροστα",
    "Κοντρα σουστες πισω",
    "Λαστιχα",
    "Γυρισμα ελαστικων",
    "Μπαταρια",
    "Μπιτε καθαριστηρων",
    "Κοντρα σουστες καπο μπροστα",
    "Κοντρα σουστες καπο πισω",
]


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = f"ERROR: {type(exc).__name__}: {exc}\n\nTRACEBACK:\n{tb}"
    return PlainTextResponse(msg, status_code=500)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    # ✅ Safe DB migration (SQLite): add exclude_from_print if missing
    try:
        with engine.connect() as conn:
            try:
                cols = conn.execute(text("PRAGMA table_info(visit_checklist_lines)")).fetchall()
                colnames = {c[1] for c in cols}
                if "exclude_from_print" not in colnames:
                    conn.execute(
                        text(
                            "ALTER TABLE visit_checklist_lines "
                            "ADD COLUMN exclude_from_print BOOLEAN NOT NULL DEFAULT 0"
                        )
                    )
                    conn.commit()
            except Exception:
                pass
    except Exception:
        pass


def seed_master_if_empty(db: Session):
    if db.query(ChecklistItem).count() == 0:
        for name in DEFAULT_CHECKLIST:
            db.add(ChecklistItem(category=DEFAULT_CATEGORY, name=name))
        db.commit()


def combine_dt(d: Optional[str], t: Optional[str]):
    d = (d or "").strip()
    t = (t or "").strip()
    if not d:
        return None
    if not t:
        t = "00:00"
    return datetime.fromisoformat(f"{d}T{t}:00")


def printable_lines(db: Session, visit_id: int):
    """
    ✅ Print/PDF rules:
    - INCLUDE if result is CHECK or REPAIR
      OR parts_code is filled
      OR parts_qty > 0
    - EXCLUDE if exclude_from_print == True
    """
    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )

    out = []
    for ln in lines:
        r = (ln.result or "OK").upper().strip()
        parts_code = (getattr(ln, "parts_code", "") or "").strip()
        parts_qty = int(getattr(ln, "parts_qty", 0) or 0)

        include = (r in ("CHECK", "REPAIR")) or (parts_code != "") or (parts_qty > 0)
        excluded = bool(getattr(ln, "exclude_from_print", False))

        if include and not excluded:
            out.append(ln)

    return out


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": None, "visits": visits})


@app.post("/visits/new")
def create_visit(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)

    v = Visit(
        job_no=f"JOB-{(db.query(Visit).count() + 1)}",
        customer_name="",
        phone="",
        email="",
        plate_number="",
        vin="",
        model="",
        km="",
        customer_complaint="",
    )
    db.add(v)
    db.commit()
    db.refresh(v)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category, ChecklistItem.name).all()
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
def visit_page(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )

    return templates.TemplateResponse("visit.html", {"request": request, "user": None, "visit": visit, "lines": lines})


@app.post("/visits/{visit_id}/save_all")
async def save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    # dates
    try:
        visit.date_in = combine_dt(form.get("date_in_date"), form.get("date_in_time"))
    except Exception:
        pass
    try:
        visit.date_out = combine_dt(form.get("date_out_date"), form.get("date_out_time"))
    except Exception:
        pass

    # visit fields
    visit.plate_number = (form.get("plate_number") or "").strip()
    visit.vin = (form.get("vin") or "").strip()
    visit.model = (form.get("model") or "").strip()
    visit.customer_name = (form.get("customer_name") or "").strip()
    visit.phone = (form.get("phone") or "").strip()
    visit.email = (form.get("email") or "").strip()
    visit.km = (form.get("km") or "").strip()
    visit.customer_complaint = (form.get("customer_complaint") or "").strip()

    # lines
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    for ln in lines:
        ln.result = (form.get(f"result_{ln.id}") or ln.result or "OK").strip()
        ln.notes = (form.get(f"notes_{ln.id}") or "").strip()
        ln.parts_code = (form.get(f"parts_code_{ln.id}") or "").strip()

        qty_raw = (form.get(f"parts_qty_{ln.id}") or "0").strip()
        try:
            ln.parts_qty = int(qty_raw) if qty_raw else 0
        except ValueError:
            ln.parts_qty = 0

        # ✅ remember exclusions (needs hidden input + checkbox in visit.html)
        ex = (form.get(f"exclude_{ln.id}") or "0").strip()
        ln.exclude_from_print = (ex == "1")

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


@app.post("/visits/{visit_id}/lines/new")
async def add_line(
    visit_id: int,
    request: Request,
    category: str = Form(...),
    item_name: str = Form(...),
    add_to_master: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return RedirectResponse("/", status_code=302)

    cat = (category or "").strip()
    name = (item_name or "").strip()

    db.add(
        VisitChecklistLine(
            visit_id=visit_id,
            category=cat,
            item_name=name,
            result="OK",
            notes="",
            parts_code="",
            parts_qty=0,
            exclude_from_print=False,
        )
    )
    if add_to_master == "1":
        db.add(ChecklistItem(category=cat, name=name))

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = printable_lines(db, visit_id)
    return templates.TemplateResponse("print.html", {"request": request, "visit": visit, "lines": lines})


@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = printable_lines(db, visit_id)

    company = {
        "name": "O&S STEPHANOU LTD",
        "lines": [
            "Michael Paridi 3, Palouriotissa",
            "Tel: 22436990-22436992",
            "Fax: 22437001",
            "Email: osstephanou@gmail.com",
            "VAT: 10079915R | TAX: 12079915T",
        ],
    }

    visit_d = {
        "job_no": visit.job_no or str(visit.id),
        "plate_number": visit.plate_number or "",
        "vin": visit.vin or "",
        "model": visit.model or "",
        "km": visit.km or "",
        "customer_name": visit.customer_name or "",
        "phone": visit.phone or "",
        "email": visit.email or "",
        "customer_complaint": visit.customer_complaint or "",
        "date_in": getattr(visit, "date_in", None),
        "date_out": getattr(visit, "date_out", None),
    }

    lines_d = []
    for ln in lines:
        lines_d.append(
            {
                "category": ln.category or "",
                "item_name": ln.item_name or "",
                "result": ln.result or "",
                "parts_code": getattr(ln, "parts_code", "") or "",
                "parts_qty": int(getattr(ln, "parts_qty", 0) or 0),
            }
        )

    pdf_bytes = build_jobcard_pdf(company, visit_d, lines_d)
    filename = f'job_{visit_d["job_no"]}.pdf'
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    q = db.query(Visit)

    df = (date_from or "").strip()
    dt = (date_to or "").strip()

    if df and dt:
        try:
            d1 = datetime.fromisoformat(df + "T00:00:00")
            d2 = datetime.fromisoformat(dt + "T23:59:59")
            q = q.filter(Visit.date_in >= d1, Visit.date_in <= d2)
        except Exception:
            pass

    visits = q.order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("history.html", {"request": request, "date_from": df, "date_to": dt, "visits": visits})


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    q2 = (q or "").strip()
    results = []
    if q2:
        like = f"%{q2}%"
        results = (
            db.query(Visit)
            .filter(
                or_(
                    Visit.customer_name.ilike(like),
                    Visit.phone.ilike(like),
                    Visit.email.ilike(like),
                    Visit.plate_number.ilike(like),
                    Visit.vin.ilike(like),
                    Visit.model.ilike(like),
                    Visit.job_no.ilike(like),
                )
            )
            .order_by(Visit.id.desc())
            .limit(200)
            .all()
        )
    return templates.TemplateResponse("search.html", {"request": request, "user": None, "q": q2, "results": results})


@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)
    items = db.query(ChecklistItem).order_by(ChecklistItem.category, ChecklistItem.name).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "user": None, "items": items})


@app.post("/checklist/add")
def checklist_add(request: Request, category: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    db.add(ChecklistItem(category=(category or "").strip(), name=(name or "").strip()))
    db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/{item_id}/update")
def checklist_update(item_id: int, request: Request, category: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        it.category = (category or "").strip()
        it.name = (name or "").strip()
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/{item_id}/delete")
def checklist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)
