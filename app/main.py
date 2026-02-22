import os
import json
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

    # ✅ Safe migration: ensure exclude_from_print exists (SQLite only)
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


def is_selected_line(ln: VisitChecklistLine) -> bool:
    r = (ln.result or "OK").upper().strip()
    parts_code = (getattr(ln, "parts_code", "") or "").strip()
    parts_qty = int(getattr(ln, "parts_qty", 0) or 0)
    include = (r in ("CHECK", "REPAIR")) or (parts_code != "") or (parts_qty > 0)
    excluded = bool(getattr(ln, "exclude_from_print", False))
    return include and not excluded


def printable_lines(db: Session, visit_id: int):
    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )
    return [ln for ln in lines if is_selected_line(ln)]


def _sqlite_db_file_path() -> Optional[str]:
    try:
        if engine.url.get_backend_name() != "sqlite":
            return None
        dbname = engine.url.database
        if not dbname or dbname == ":memory:":
            return None
        if os.path.isabs(dbname):
            return dbname
        return os.path.abspath(dbname)
    except Exception:
        return None


@app.get("/backup")
def backup(db: Session = Depends(get_db)):
    """
    ✅ Backup:
    - SQLite: download .db (full backup)
    - Otherwise: JSON export
    """
    sqlite_path = _sqlite_db_file_path()
    now = datetime.now().strftime("%Y-%m-%d_%H%M")

    if sqlite_path and os.path.exists(sqlite_path):
        with open(sqlite_path, "rb") as f:
            data = f.read()
        filename = f"stefanos_backup_{now}.db"
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    visits = db.query(Visit).order_by(Visit.id.asc()).all()
    lines = db.query(VisitChecklistLine).order_by(VisitChecklistLine.id.asc()).all()
    items = db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()

    def dt(v):
        return v.isoformat() if v else None

    payload = {
        "exported_at": datetime.now().isoformat(),
        "engine": str(engine.url),
        "visits": [
            {
                "id": v.id,
                "job_no": getattr(v, "job_no", None),
                "date_in": dt(getattr(v, "date_in", None)),
                "date_out": dt(getattr(v, "date_out", None)),
                "plate_number": getattr(v, "plate_number", ""),
                "vin": getattr(v, "vin", ""),
                "model": getattr(v, "model", ""),
                "km": getattr(v, "km", ""),
                "customer_name": getattr(v, "customer_name", ""),
                "phone": getattr(v, "phone", ""),
                "email": getattr(v, "email", ""),
                "customer_complaint": getattr(v, "customer_complaint", ""),
            }
            for v in visits
        ],
        "visit_checklist_lines": [
            {
                "id": ln.id,
                "visit_id": ln.visit_id,
                "category": ln.category,
                "item_name": ln.item_name,
                "result": ln.result,
                "notes": ln.notes,
                "parts_code": getattr(ln, "parts_code", ""),
                "parts_qty": int(getattr(ln, "parts_qty", 0) or 0),
                "exclude_from_print": bool(getattr(ln, "exclude_from_print", False)),
            }
            for ln in lines
        ],
        "checklist_items": [{"id": it.id, "category": it.category, "name": it.name} for it in items],
    }

    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"stefanos_backup_{now}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "visits": visits})


@app.post("/visits/new")
def create_visit(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)

    v = Visit(
        job_no=f"JOB-{(db.query(Visit).count() + 1)}",
        date_in=datetime.now(),  # ✅ auto now
        date_out=None,
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

    # ✅ default to selected view
    return RedirectResponse(f"/visits/{v.id}?mode=selected", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_page(visit_id: int, request: Request, mode: str = "selected", db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    all_lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )

    if (mode or "selected").lower() == "all":
        lines = all_lines
        mode = "all"
    else:
        lines = [ln for ln in all_lines if is_selected_line(ln)]
        mode = "selected"

    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": visit, "lines": lines, "mode": mode},
    )


@app.post("/visits/{visit_id}/save_all")
async def save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    """
    ✅ Saves everything.
    ✅ If action == add_line: adds new line AFTER saving (so nothing is lost).
    ✅ after_save: stay | print | pdf
    """
    form = await request.form()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    # dates
    visit.date_in = combine_dt(form.get("date_in_date"), form.get("date_in_time"))
    visit.date_out = combine_dt(form.get("date_out_date"), form.get("date_out_time"))

    # visit fields
    visit.plate_number = (form.get("plate_number") or "").strip()
    visit.vin = (form.get("vin") or "").strip()
    visit.model = (form.get("model") or "").strip()
    visit.customer_name = (form.get("customer_name") or "").strip()
    visit.phone = (form.get("phone") or "").strip()
    visit.email = (form.get("email") or "").strip()
    visit.km = (form.get("km") or "").strip()
    visit.customer_complaint = (form.get("customer_complaint") or "").strip()

    # lines save
    all_lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    for ln in all_lines:
        ln.result = (form.get(f"result_{ln.id}") or ln.result or "OK").strip()
        ln.notes = (form.get(f"notes_{ln.id}") or "").strip()
        ln.parts_code = (form.get(f"parts_code_{ln.id}") or "").strip()

        qty_raw = (form.get(f"parts_qty_{ln.id}") or "0").strip()
        try:
            ln.parts_qty = int(qty_raw) if qty_raw else 0
        except ValueError:
            ln.parts_qty = 0

        ex = (form.get(f"exclude_{ln.id}") or "0").strip()
        ln.exclude_from_print = (ex == "1")

    # ✅ optional add new line AFTER saving (so no lost selections)
    action = (form.get("action") or "").strip().lower()
    if action == "add_line":
        cat = (form.get("new_category") or "").strip()
        name = (form.get("new_item_name") or "").strip()
        add_master = (form.get("new_add_to_master") or "0").strip() == "1"
        if cat and name:
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
            if add_master:
                db.add(ChecklistItem(category=cat, name=name))

    db.commit()

    after = (form.get("after_save") or "stay").strip().lower()
    if after == "print":
        return RedirectResponse(f"/visits/{visit_id}/print", status_code=302)
    if after == "pdf":
        return RedirectResponse(f"/visits/{visit_id}/pdf", status_code=302)

    # ✅ after saving go to selected view (as you want)
    return RedirectResponse(f"/visits/{visit_id}?mode=selected", status_code=302)


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
        # ✅ IMPORTANT: use plain text, no '&' parsing issues
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
                "result": (ln.result or "").strip(),
                "parts_code": (getattr(ln, "parts_code", "") or "").strip(),
                "parts_qty": int(getattr(ln, "parts_qty", 0) or 0),
                "notes": (ln.notes or "").strip(),
            }
        )

    pdf_bytes = build_jobcard_pdf(company, visit_d, lines_d)
    filename = f'job_{visit_d["job_no"]}.pdf'
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
