import os
import json
import traceback
from datetime import datetime
from typing import Optional, Dict, Tuple, List

from fastapi import FastAPI, Request, Depends, Response, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from sqlalchemy.orm import Session
from sqlalchemy import or_, text, func

from .db import get_db, engine
from .models import Base, ChecklistItem, Visit, VisitChecklistLine, PartMemory
from .pdf_utils import build_jobcard_pdf

app = FastAPI()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
from fastapi.templating import Jinja2Templates
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


def norm_model_key(model: str) -> str:
    return (model or "").strip().lower()


def seed_master_if_empty(db: Session):
    if db.query(ChecklistItem).count() == 0:
        for name in DEFAULT_CHECKLIST:
            db.add(ChecklistItem(category=DEFAULT_CATEGORY, name=name))
        db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    # ensure needed columns exist (sqlite ALTERs are safe in try)
    try:
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(visit_checklist_lines)")).fetchall()
            colnames = {c[1] for c in cols}
            if "parts_code" not in colnames:
                conn.execute(text("ALTER TABLE visit_checklist_lines ADD COLUMN parts_code VARCHAR"))
            if "parts_qty" not in colnames:
                conn.execute(text("ALTER TABLE visit_checklist_lines ADD COLUMN parts_qty INTEGER NOT NULL DEFAULT 0"))
            if "exclude_from_print" not in colnames:
                conn.execute(text("ALTER TABLE visit_checklist_lines ADD COLUMN exclude_from_print BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
    except Exception:
        pass

    gen = get_db()
    db = next(gen)
    try:
        seed_master_if_empty(db)
    finally:
        try:
            gen.close()
        except Exception:
            pass


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
    parts_code = (ln.parts_code or "").strip()
    try:
        parts_qty = int(ln.parts_qty or 0)
    except Exception:
        parts_qty = 0

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


@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py"}


@app.get("/__dbinfo")
def __dbinfo(db: Session = Depends(get_db)):
    # δείχνει τι DB χρησιμοποιεί πραγματικά το service
    driver = (engine.url.drivername or "").lower()
    url = str(engine.url)

    # για ασφάλεια, κρύβουμε password αν υπάρχει
    safe_url = url
    try:
        if "://" in url and "@" in url:
            prefix, rest = url.split("://", 1)
            creds, host = rest.split("@", 1)
            if ":" in creds:
                user, _pwd = creds.split(":", 1)
                safe_url = f"{prefix}://{user}:***@{host}"
    except Exception:
        pass

    visits_count = db.execute(text("SELECT COUNT(*) FROM visits")).scalar() if table_exists(db, "visits") else None

    return {
        "driver": driver,
        "database_url": safe_url,
        "visits_count": visits_count,
    }


def table_exists(db: Session, table_name: str) -> bool:
    try:
        # works in sqlite/postgres
        db.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
        return True
    except Exception:
        return False


# ---------------------------
# BACKUP (EXPORT)
# ---------------------------
@app.get("/backup")
def backup_export(db: Session = Depends(get_db)):
    # JSON export (safe + portable)
    visits = db.query(Visit).order_by(Visit.id.asc()).all()
    lines = db.query(VisitChecklistLine).order_by(VisitChecklistLine.id.asc()).all()
    items = db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()
    mems = db.query(PartMemory).order_by(PartMemory.id.asc()).all()

    def dt(v):
        return v.isoformat() if v else None

    payload = {
        "exported_at": datetime.now().isoformat(),
        "engine": str(engine.url),
        "visits": [
            {
                "id": v.id,
                "job_no": v.job_no,
                "date_in": dt(v.date_in),
                "date_out": dt(v.date_out),
                "plate_number": v.plate_number,
                "vin": v.vin,
                "model": v.model,
                "km": v.km,
                "customer_name": v.customer_name,
                "phone": v.phone,
                "email": v.email,
                "customer_complaint": v.customer_complaint,
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
                "parts_code": ln.parts_code,
                "parts_qty": int(ln.parts_qty or 0),
                "exclude_from_print": bool(getattr(ln, "exclude_from_print", False)),
            }
            for ln in lines
        ],
        "checklist_items": [{"id": it.id, "category": it.category, "name": it.name} for it in items],
        "part_memories": [
            {
                "id": m.id,
                "model_key": m.model_key,
                "category": m.category,
                "item_name": m.item_name,
                "parts_code": m.parts_code,
                "updated_at": dt(m.updated_at),
            }
            for m in mems
        ],
    }

    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    now = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"stephanou_backup_{now}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------
# BACKUP (IMPORT JSON)
# ---------------------------
@app.post("/backup/import")
async def backup_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = (file.filename or "").lower()
    data = await file.read()

    if not filename.endswith(".json"):
        return PlainTextResponse("Import επιτρέπεται μόνο για JSON backup (.json).", status_code=400)

    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return PlainTextResponse("Το αρχείο δεν είναι έγκυρο JSON.", status_code=400)

    db.query(VisitChecklistLine).delete()
    db.query(Visit).delete()

    visits_by_old_id: Dict[int, Visit] = {}
    for v in payload.get("visits", []):
        nv = Visit(
            job_no=v.get("job_no"),
            date_in=datetime.fromisoformat(v["date_in"]) if v.get("date_in") else None,
            date_out=datetime.fromisoformat(v["date_out"]) if v.get("date_out") else None,
            plate_number=v.get("plate_number"),
            vin=v.get("vin"),
            model=v.get("model"),
            km=v.get("km"),
            customer_name=v.get("customer_name"),
            phone=v.get("phone"),
            email=v.get("email"),
            customer_complaint=v.get("customer_complaint"),
        )
        db.add(nv)
        db.flush()
        try:
            visits_by_old_id[int(v.get("id"))] = nv
        except Exception:
            pass

    for ln in payload.get("visit_checklist_lines", []):
        old_vid = ln.get("visit_id")
        if old_vid is None:
            continue
        new_visit = visits_by_old_id.get(int(old_vid))
        if not new_visit:
            continue
        nln = VisitChecklistLine(
            visit_id=new_visit.id,
            category=ln.get("category"),
            item_name=ln.get("item_name"),
            result=ln.get("result"),
            notes=ln.get("notes"),
            parts_code=ln.get("parts_code"),
            parts_qty=int(ln.get("parts_qty") or 0),
            exclude_from_print=bool(ln.get("exclude_from_print") or False),
        )
        db.add(nln)

    db.query(PartMemory).delete()
    for m in payload.get("part_memories", []):
        mk = (m.get("model_key") or "").strip().lower()
        cat = (m.get("category") or "").strip()
        nm = (m.get("item_name") or "").strip()
        pc = (m.get("parts_code") or "").strip()
        if mk and cat and nm and pc:
            nmobj = PartMemory(
                model_key=mk,
                category=cat,
                item_name=nm,
                parts_code=pc,
                updated_at=datetime.fromisoformat(m["updated_at"]) if m.get("updated_at") else datetime.utcnow(),
            )
            db.add(nmobj)

    db.commit()
    return RedirectResponse("/", status_code=302)


# ---------------------------
# RESET (SECURE + HARD DELETE)
# ---------------------------
@app.post("/reset")
async def reset_data(
    reset_password: str = Form(""),
    keep_master: str = Form("1"),
    db: Session = Depends(get_db),
):
    expected = (os.getenv("RESET_PASSWORD") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="Reset disabled: RESET_PASSWORD is not set.")

    if (reset_password or "").strip() != expected:
        raise HTTPException(status_code=403, detail="Λάθος κωδικός για Reset.")

    # κλείνουμε session για να μην κρατά cache
    try:
        db.rollback()
    except Exception:
        pass
    try:
        db.close()
    except Exception:
        pass

    driver = (engine.url.drivername or "").lower()

    if driver.startswith("postgresql"):
        with engine.begin() as conn:
            # ΣΒΗΝΕΙ ΟΛΟ ΤΟ ΙΣΤΟΡΙΚΟ (visits + lines) με CASCADE
            # (TRUNCATE είναι πιο σίγουρο από DELETE σε Postgres)
            conn.execute(text("TRUNCATE TABLE visit_checklist_lines RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE visits RESTART IDENTITY CASCADE;"))

            # Αν θέλεις να σβήνει ΚΑΙ τα memories + master checklist
            if keep_master.strip() == "0":
                conn.execute(text("TRUNCATE TABLE part_memories RESTART IDENTITY CASCADE;"))
                conn.execute(text("TRUNCATE TABLE checklist_items RESTART IDENTITY CASCADE;"))
    else:
        # fallback
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM visit_checklist_lines"))
            conn.execute(text("DELETE FROM visits"))
            if keep_master.strip() == "0":
                conn.execute(text("DELETE FROM part_memories"))
                conn.execute(text("DELETE FROM checklist_items"))

    return RedirectResponse("/", status_code=302)
# ---------------------------
# PAGES
# ---------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", db: Session = Depends(get_db)):
    seed_master_if_empty(db)
    q_clean = (q or "").strip()
    query = db.query(Visit)

    if q_clean:
        like = f"%{q_clean.lower()}%"
        query = query.filter(
            or_(
                func.lower(Visit.customer_name).like(like),
                func.lower(Visit.plate_number).like(like),
                func.lower(Visit.phone).like(like),
                func.lower(Visit.email).like(like),
                func.lower(Visit.model).like(like),
                func.lower(Visit.vin).like(like),
                func.lower(Visit.job_no).like(like),
            )
        )

    visits = query.order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "visits": visits, "q": q_clean})


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    return index(request=request, q=q, db=db)


@app.post("/visits/new")
def create_visit(db: Session = Depends(get_db)):
    seed_master_if_empty(db)

    v = Visit(job_no=f"JOB-{(db.query(Visit).count() + 1)}")
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
    return RedirectResponse(f"/visits/{v.id}?mode=all", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_page(visit_id: int, request: Request, mode: str = "all", cats: str = "", db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    all_lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category.asc(), VisitChecklistLine.id.asc())
        .all()
    )

    categories = sorted({(ln.category or "").strip() for ln in all_lines if (ln.category or "").strip()})

    selected_cats: List[str] = []
    cats_raw = (cats or "").strip()
    if cats_raw:
        selected_cats = [c.strip() for c in cats_raw.split(",") if c.strip()]

    mk = norm_model_key(visit.model or "")
    if mk:
        mems = db.query(PartMemory).filter(PartMemory.model_key == mk).all()
        mem_map: Dict[Tuple[str, str], str] = {}
        for m in mems:
            mem_map[(m.category, m.item_name)] = m.parts_code

        changed = False
        for ln in all_lines:
            if (ln.parts_code or "").strip():
                continue
            key = ((ln.category or "").strip(), (ln.item_name or "").strip())
            if key in mem_map:
                ln.parts_code = mem_map[key]
                changed = True
        if changed:
            db.commit()

    mode = (mode or "all").lower().strip()
    if mode == "selected":
        filtered = [ln for ln in all_lines if is_selected_line(ln)]
        lines0 = filtered if filtered else all_lines
    else:
        mode = "all"
        lines0 = all_lines

    if selected_cats:
        lines = [ln for ln in lines0 if (ln.category or "").strip() in selected_cats]
    else:
        lines = lines0

    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": visit, "lines": lines, "mode": mode, "categories": categories, "selected_cats": selected_cats},
    )


@app.post("/visits/{visit_id}/save_all")
async def save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    mode = (form.get("mode") or "all").strip().lower()
    if mode not in ("selected", "all"):
        mode = "all"

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    visit.date_in = combine_dt(form.get("date_in_date"), form.get("date_in_time"))
    visit.date_out = combine_dt(form.get("date_out_date"), form.get("date_out_time"))

    visit.plate_number = (form.get("plate_number") or "").strip()
    visit.vin = (form.get("vin") or "").strip()
    visit.model = (form.get("model") or "").strip()
    visit.km = (form.get("km") or "").strip()

    visit.customer_name = (form.get("customer_name") or "").strip()
    visit.phone = (form.get("phone") or "").strip()
    visit.email = (form.get("email") or "").strip()
    visit.customer_complaint = (form.get("customer_complaint") or "").strip()

    mk = norm_model_key(visit.model or "")

    all_lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()

    for ln in all_lines:
        if f"result_{ln.id}" in form:
            ln.result = (form.get(f"result_{ln.id}") or "OK").strip()
        if f"notes_{ln.id}" in form:
            ln.notes = (form.get(f"notes_{ln.id}") or "").strip()
        if f"parts_code_{ln.id}" in form:
            ln.parts_code = (form.get(f"parts_code_{ln.id}") or "").strip()
        if f"parts_qty_{ln.id}" in form:
            qty_raw = (form.get(f"parts_qty_{ln.id}") or "0").strip()
            try:
                ln.parts_qty = int(qty_raw) if qty_raw else 0
            except ValueError:
                ln.parts_qty = 0

        ln.exclude_from_print = (form.get(f"exclude_{ln.id}") == "1")

        pc = (ln.parts_code or "").strip()
        cat = (ln.category or "").strip()
        nm = (ln.item_name or "").strip()
        if mk and pc and cat and nm:
            mem = (
                db.query(PartMemory)
                .filter(PartMemory.model_key == mk, PartMemory.category == cat, PartMemory.item_name == nm)
                .first()
            )
            if not mem:
                db.add(PartMemory(model_key=mk, category=cat, item_name=nm, parts_code=pc, updated_at=datetime.utcnow()))
            else:
                mem.parts_code = pc
                mem.updated_at = datetime.utcnow()

    action = (form.get("action") or "").strip().lower()
    if action == "add_line":
        cat = (form.get("new_category") or "").strip()
        name = (form.get("new_item_name") or "").strip()
        add_master = (form.get("new_add_to_master") or "0").strip() == "1"
        if cat and name:
            db.add(VisitChecklistLine(visit_id=visit_id, category=cat, item_name=name, result="CHECK"))
            if add_master:
                db.add(ChecklistItem(category=cat, name=name))

    db.commit()

    after = (form.get("after_save") or "stay").strip().lower()
    if after == "print":
        return RedirectResponse(f"/visits/{visit_id}/print", status_code=302)
    if after == "pdf":
        return RedirectResponse(f"/visits/{visit_id}/pdf", status_code=302)

    if action == "add_line":
        return RedirectResponse(f"/visits/{visit_id}?mode={mode}#addnew", status_code=302)

    return RedirectResponse(f"/visits/{visit_id}?mode={mode}", status_code=302)


@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)
    lines = printable_lines(db, visit_id)
    return templates.TemplateResponse("print.html", {"request": request, "visit": visit, "lines": lines})


@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, db: Session = Depends(get_db)):
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
        "date_in": visit.date_in,
        "date_out": visit.date_out,
    }

    lines_d = []
    for ln in lines:
        lines_d.append(
            {
                "category": ln.category or "",
                "item_name": ln.item_name or "",
                "result": (ln.result or "").strip(),
                "parts_code": (ln.parts_code or "").strip(),
                "parts_qty": int(ln.parts_qty or 0),
                "notes": (ln.notes or "").strip(),
            }
        )

    pdf_bytes = build_jobcard_pdf(company, visit_d, lines_d)
    filename = f'job_{visit_d["job_no"]}.pdf'
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.get("/checklist", response_class=HTMLResponse)
def checklist_page(request: Request, db: Session = Depends(get_db)):
    seed_master_if_empty(db)
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.name.asc()).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "items": items})


@app.post("/checklist/add")
async def checklist_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat = (form.get("category") or "").strip()
    name = (form.get("name") or "").strip()
    if cat and name:
        db.add(ChecklistItem(category=cat, name=name))
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/delete")
async def checklist_delete(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    item_id = (form.get("item_id") or "").strip()
    try:
        iid = int(item_id)
    except ValueError:
        return RedirectResponse("/checklist", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == iid).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, from_date: str = "", to_date: str = "", q: str = "", db: Session = Depends(get_db)):
    query = db.query(Visit)

    if from_date.strip():
        try:
            dt_from = datetime.fromisoformat(from_date.strip() + "T00:00:00")
            query = query.filter(Visit.date_in >= dt_from)
        except Exception:
            pass

    if to_date.strip():
        try:
            dt_to = datetime.fromisoformat(to_date.strip() + "T23:59:59")
            query = query.filter(Visit.date_in <= dt_to)
        except Exception:
            pass

    q_clean = (q or "").strip()
    if q_clean:
        like = f"%{q_clean.lower()}%"
        query = query.filter(
            or_(
                func.lower(Visit.customer_name).like(like),
                func.lower(Visit.plate_number).like(like),
                func.lower(Visit.phone).like(like),
                func.lower(Visit.email).like(like),
                func.lower(Visit.model).like(like),
                func.lower(Visit.vin).like(like),
                func.lower(Visit.job_no).like(like),
            )
        )

    visits = query.order_by(Visit.id.desc()).limit(500).all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "visits": visits, "from_date": from_date, "to_date": to_date, "q": q_clean},
    )
