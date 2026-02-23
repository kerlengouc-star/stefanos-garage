import os
import io
import json
import datetime as dt
from typing import Optional, Any, Tuple, List

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm import Session
from sqlalchemy import inspect, or_, text

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from .db import SessionLocal, engine, Base

# IMPORTANT: Models — User is OPTIONAL (κάποια repos δεν έχουν User)
try:
    from .models import User  # type: ignore
    HAS_USER = True
except Exception:
    User = None  # type: ignore
    HAS_USER = False

from .models import ChecklistItem, Visit, VisitChecklistLine


app = FastAPI()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="app/templates")


# ----------------------------
# DB
# ----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    # Fix "no such table"
    Base.metadata.create_all(bind=engine)


# ----------------------------
# Auth (optional)
# ----------------------------
def get_current_user(request: Request, db: Session) -> Optional[Any]:
    if not HAS_USER:
        return {"ok": True}  # dummy user
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def require_user(request: Request, db: Session) -> Optional[Any]:
    if not HAS_USER:
        return {"ok": True}
    return get_current_user(request, db)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if not HAS_USER:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    if not HAS_USER:
        return RedirectResponse("/", status_code=302)

    # Πολύ απλό login: αν έχεις άλλο σύστημα auth, το αλλάζουμε μετά.
    u = db.query(User).filter(getattr(User, "email") == email).first()  # type: ignore
    if not u:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Λάθος στοιχεία"})

    # Εδώ ΔΕΝ κάνουμε password verify γιατί δεν ξέρουμε το schema σου.
    # Για τώρα: επιτρέπουμε login μόνο αν το password ταιριάζει σε ένα πιθανό field.
    ok = False
    for field in ["password", "password_hash", "hashed_password"]:
        if hasattr(u, field) and (getattr(u, field) or "") == password:
            ok = True
            break

    if not ok:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Λάθος στοιχεία"})

    request.session["user_id"] = getattr(u, "id")
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login" if HAS_USER else "/", status_code=302)


# ----------------------------
# Debug
# ----------------------------
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


# ----------------------------
# Pages
# ----------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": u, "visits": visits})


@app.get("/visits/new")
def visit_new(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

    now = dt.datetime.now()

    v = Visit()
    if hasattr(v, "date_in"):
        setattr(v, "date_in", now.date().isoformat())
    if hasattr(v, "time_in"):
        setattr(v, "time_in", now.strftime("%H:%M"))
    if hasattr(v, "status"):
        setattr(v, "status", "open")

    db.add(v)
    db.commit()
    db.refresh(v)
    return RedirectResponse(f"/visits/{v.id}", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()

    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in lines if getattr(ln, "checklist_item_id", None) is not None}

    return templates.TemplateResponse(
        "visit.html",
        {
            "request": request,
            "user": u,
            "visit": visit,
            "items": items,
            "line_by_item": line_by_item,
            "now_time": dt.datetime.now().strftime("%H:%M"),
            "now_date": dt.date.today().isoformat(),
        },
    )


# ----------------------------
# SAVE ALL
# ----------------------------
@app.post("/visits/{visit_id}/save_all")
async def visit_save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = dict(await request.form())

    def set_if(field: str, val: Any):
        if hasattr(visit, field):
            setattr(visit, field, val)

    # Basic visit fields (safe)
    for f in [
        "job_no", "plate_number", "vin", "customer_name", "phone",
        "email", "model", "km", "customer_complaint", "notes_general",
        "date_in", "time_in", "date_out", "time_out",
        "total_parts", "total_labor", "total_amount", "status"
    ]:
        if f in form:
            set_if(f, (form.get(f) or "").strip())

    # If time/date empty -> fill now (computer time)
    now = dt.datetime.now()
    if hasattr(visit, "date_in") and not getattr(visit, "date_in", ""):
        set_if("date_in", now.date().isoformat())
    if hasattr(visit, "time_in") and not getattr(visit, "time_in", ""):
        set_if("time_in", now.strftime("%H:%M"))

    # Add new checklist item (without wiping anything)
    new_category = (form.get("new_category") or "").strip()
    new_item_name = (form.get("new_item_name") or "").strip()
    if new_category and new_item_name:
        exists = (
            db.query(ChecklistItem)
            .filter(ChecklistItem.category == new_category)
            .filter(ChecklistItem.name == new_item_name)
            .first()
        )
        if not exists:
            db.add(ChecklistItem(category=new_category, name=new_item_name))
            db.commit()

    # Save checklist lines
    items = db.query(ChecklistItem).all()
    existing_lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in existing_lines if getattr(ln, "checklist_item_id", None) is not None}

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


# ----------------------------
# Checklist admin
# ----------------------------
@app.get("/checklist", response_class=HTMLResponse)
def checklist_page(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


# ----------------------------
# Search
# ----------------------------
@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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


# ----------------------------
# Print / PDF (only selected items that have data)
# ----------------------------
def _selected_lines(db: Session, visit_id: int) -> List[Tuple[ChecklistItem, VisitChecklistLine]]:
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in lines if getattr(ln, "checklist_item_id", None) is not None}

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
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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
    c.drawString(40, y, "JOB CARD - Stephanou Garage")
    y -= 22

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

    y -= 8
    line("Πελάτης", getattr(visit, "customer_name", ""))
    line("Τηλέφωνο", getattr(visit, "phone", ""))
    line("Email", getattr(visit, "email", ""))
    line("Αρ. Πινακίδας", getattr(visit, "plate_number", ""))
    line("Μοντέλο", getattr(visit, "model", ""))
    line("KM", getattr(visit, "km", ""))

    y -= 10
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
            parts_txt = f" | Κωδικός: {pcode} | Ποσ.: {pqty}"
        notes_txt = f" | Σημ.: {notes}" if notes else ""
        ok_txt = " | OK" if checked else ""

        txt = f"- [{it.category}] {it.name}{ok_txt}{parts_txt}{notes_txt}"

        if y < 60:
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 10)

        c.drawString(40, y, txt[:150])
        y -= 14

    c.showPage()
    c.save()
    return buf.getvalue()


@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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


# ----------------------------
# Backup / Import
# ----------------------------
@app.get("/backup")
def backup_download(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

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
    if not u and HAS_USER:
        return RedirectResponse("/login", status_code=302)

    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    # checklist items
    for it in payload.get("checklist_items", []):
        category = (it.get("category") or "").strip()
        name = (it.get("name") or "").strip()
        if not category or not name:
            continue
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
            db.add(ChecklistItem(category=category, name=name))
    db.commit()

    # visits (best effort)
    for v in payload.get("visits", []):
        obj = Visit()
        for k, val in v.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    # lines (best effort)
    for ln in payload.get("visit_lines", []):
        obj = VisitChecklistLine()
        for k, val in ln.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    return RedirectResponse("/", status_code=302)
@app.post("/reset-test")
def reset_test(
    request: Request,
    db: Session = Depends(get_db),
    code: str = Form(""),
):
    """
    Σβήνει ΟΛΑ τα test δεδομένα (ιστορικό):
    - visits
    - visit checklist lines
    ΔΕΝ σβήνει τις κατηγορίες/λίστα ChecklistItem.
    """
    # Αν έχεις login system, σεβόμαστε το ίδιο require_user:
    u = require_user(request, db)
    if not u and globals().get("HAS_USER", False):
        return RedirectResponse("/login", status_code=302)

    RESET_CODE = os.getenv("RESET_CODE", "")
    if not RESET_CODE or code != RESET_CODE:
        return JSONResponse({"ok": False, "error": "Wrong code"}, status_code=403)

    try:
        driver = (engine.url.drivername or "").lower()

        # παίρνουμε ακριβή table names από τα SQLAlchemy models (πολύ σημαντικό)
        visits_table = Visit.__table__.name
        lines_table = VisitChecklistLine.__table__.name

        if driver.startswith("postgresql"):
            # TRUNCATE είναι το πιο “σίγουρο” για Postgres
            # CASCADE για να καθαρίσει σωστά relations
            db.execute(text(f'TRUNCATE TABLE "{lines_table}" RESTART IDENTITY CASCADE;'))
            db.execute(text(f'TRUNCATE TABLE "{visits_table}" RESTART IDENTITY CASCADE;'))
            db.commit()
        else:
            # SQLite / άλλες: DELETE + commit
            db.query(VisitChecklistLine).delete(synchronize_session=False)
            db.query(Visit).delete(synchronize_session=False)
            db.commit()

        # επιβεβαίωση
        remaining_visits = db.query(Visit).count()
        remaining_lines = db.query(VisitChecklistLine).count()

        return {
            "ok": True,
            "message": "Reset completed",
            "remaining_visits": remaining_visits,
            "remaining_lines": remaining_lines,
            "driver": driver,
        }

    except Exception as e:
        db.rollback()
        return JSONResponse(
            {"ok": False, "error": f"{type(e).__name__}: {e}"},
            status_code=500,
        )
