import os
import io
import json
import datetime as dt
from typing import Optional, Any

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm import Session
from sqlalchemy import inspect, or_, text

from passlib.context import CryptContext

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from .db import SessionLocal, engine, Base
from .models import User, ChecklistItem, Visit, VisitChecklistLine


# ----------------------------
# App / Templates / Security
# ----------------------------
app = FastAPI()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="app/templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ----------------------------
# DB Dependency
# ----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------
# Auth helpers (session-based)
# ----------------------------
def get_current_user(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def require_user(request: Request, db: Session) -> Optional[User]:
    u = get_current_user(request, db)
    return u


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def ensure_admin(db: Session):
    """
    Δημιουργεί admin αν δεν υπάρχει.
    Περιμένει columns στο User: email, password_hash (ή password_hash-like), role.
    Αν το δικό σου User model έχει αλλιώς όνομα στο password field, άλλαξε το ΜΟΝΟ εδώ.
    """
    admin_email = os.getenv("ADMIN_EMAIL", "admin@garage.local")
    admin_pass = os.getenv("ADMIN_PASSWORD", "1234")
    admin_role = os.getenv("ADMIN_ROLE", "admin")

    u = db.query(User).filter(User.email == admin_email).first()
    if u:
        return

    # προσπαθούμε να γράψουμε password στο πιο πιθανό field name
    pw_hash = hash_password(admin_pass)

    created = None
    for field in ["password_hash", "hashed_password", "password", "passwordHash"]:
        if hasattr(User, field):
            kwargs = {"email": admin_email, field: pw_hash}
            if hasattr(User, "role"):
                kwargs["role"] = admin_role
            created = User(**kwargs)
            break

    if created is None:
        # fallback: μόνο email + role, χωρίς password (δεν θα μπορεί login)
        kwargs = {"email": admin_email}
        if hasattr(User, "role"):
            kwargs["role"] = admin_role
        created = User(**kwargs)

    db.add(created)
    db.commit()


@app.on_event("startup")
def on_startup():
    # δημιουργία πινάκων (fix για "no such table: visits")
    Base.metadata.create_all(bind=engine)

    # ensure admin
    db = SessionLocal()
    try:
        ensure_admin(db)
    finally:
        db.close()


# ----------------------------
# Debug endpoints
# ----------------------------
@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py"}


@app.get("/__dbinfo")
def __dbinfo(db: Session = Depends(get_db)):
    try:
        url = str(engine.url)
        driver = engine.url.drivername
    except Exception:
        url = "unknown"
        driver = "unknown"

    info: dict[str, Any] = {"driver": driver, "database_url": url}
    try:
        info["visits_count"] = db.query(Visit).count()
    except Exception as e:
        info["visits_count_error"] = str(e)

    return info


@app.get("/__tables")
def __tables(db: Session = Depends(get_db)):
    """
    Δείχνει όλους τους πίνακες + πόσες εγγραφές έχει ο καθένας.
    """
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
# Pages: Login / Logout
# ----------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    u = db.query(User).filter(User.email == email).first()
    if not u:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Λάθος email/κωδικός"})

    # βρίσκουμε ποιο field κρατά hash
    hashed = None
    for field in ["password_hash", "hashed_password", "password"]:
        if hasattr(u, field):
            hashed = getattr(u, field)
            break

    if not hashed or not verify_password(password, hashed):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Λάθος email/κωδικός"})

    request.session["user_id"] = u.id
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ----------------------------
# Index (list visits)
# ----------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": u, "visits": visits})


# ----------------------------
# Create / View Visit
# ----------------------------
@app.get("/visits/new")
def visit_new(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    now = dt.datetime.now()

    # fields based on your Visit model; missing fields are ignored safely
    v = Visit()
    if hasattr(v, "date_in"):
        v.date_in = now.date().isoformat()
    if hasattr(v, "time_in"):
        v.time_in = now.strftime("%H:%M")
    if hasattr(v, "status"):
        v.status = "open"

    db.add(v)
    db.commit()
    db.refresh(v)
    return RedirectResponse(f"/visits/{v.id}", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    # categories/items
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()

    # lines for this visit
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
# SAVE ALL (single button)
# ----------------------------
@app.post("/visits/{visit_id}/save_all")
async def visit_save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    form = dict(await request.form())

    # --- Update visit fields (safe set if exists)
    def set_if(field: str, val: Any):
        if hasattr(visit, field):
            setattr(visit, field, val)

    set_if("job_no", form.get("job_no", getattr(visit, "job_no", "")).strip())
    set_if("plate_number", form.get("plate_number", getattr(visit, "plate_number", "")).strip())
    set_if("vin", form.get("vin", getattr(visit, "vin", "")).strip())
    set_if("customer_name", form.get("customer_name", getattr(visit, "customer_name", "")).strip())
    set_if("phone", form.get("phone", getattr(visit, "phone", "")).strip())
    set_if("email", form.get("email", getattr(visit, "email", "")).strip())
    set_if("model", form.get("model", getattr(visit, "model", "")).strip())
    set_if("km", form.get("km", getattr(visit, "km", "")).strip())

    # rename label issue: "Παράπονο πελάτη" -> "Απαίτηση πελάτη" is template label,
    # but field stays customer_complaint
    set_if("customer_complaint", form.get("customer_complaint", getattr(visit, "customer_complaint", "")).strip())
    set_if("notes_general", form.get("notes_general", getattr(visit, "notes_general", "")).strip())

    # dates/times
    # want computer time - if empty, fill now
    now = dt.datetime.now()
    if hasattr(visit, "date_in"):
        set_if("date_in", form.get("date_in") or getattr(visit, "date_in", None) or now.date().isoformat())
    if hasattr(visit, "time_in"):
        set_if("time_in", form.get("time_in") or getattr(visit, "time_in", None) or now.strftime("%H:%M"))
    if hasattr(visit, "date_out"):
        set_if("date_out", form.get("date_out") or getattr(visit, "date_out", "") )
    if hasattr(visit, "time_out"):
        set_if("time_out", form.get("time_out") or getattr(visit, "time_out", "") )

    # totals
    set_if("total_parts", form.get("total_parts", getattr(visit, "total_parts", "")).strip())
    set_if("total_labor", form.get("total_labor", getattr(visit, "total_labor", "")).strip())
    set_if("total_amount", form.get("total_amount", getattr(visit, "total_amount", "")).strip())

    # --- Optional: add new category/item (without wiping selections)
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
            it = ChecklistItem(category=new_category, name=new_item_name)
            db.add(it)
            db.commit()

    # --- Save checklist lines
    items = db.query(ChecklistItem).all()
    existing_lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in existing_lines if getattr(ln, "checklist_item_id", None) is not None}

    for it in items:
        cid = it.id
        checked = form.get(f"chk_{cid}") == "on" or form.get(f"chk_{cid}") == "1"
        notes = (form.get(f"notes_{cid}") or "").strip()

        # parts_code + parts_qty (your new schema)
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
    if not u:
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
    if not u:
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
    if not u:
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
    if not u:
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
# History (date range)
# ----------------------------
@app.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    q = db.query(Visit)

    # if Visit.date_in is stored as string (ISO), this still works lexicographically for YYYY-MM-DD
    if date_from:
        q = q.filter(Visit.date_in >= date_from)
    if date_to:
        q = q.filter(Visit.date_in <= date_to)

    visits = q.order_by(Visit.id.desc()).limit(500).all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "user": u, "date_from": date_from, "date_to": date_to, "visits": visits},
    )


# ----------------------------
# Print (HTML like PDF)
# ----------------------------
@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in lines if getattr(ln, "checklist_item_id", None) is not None}

    # Only selected lines (checked OR has parts info OR notes)
    selected = []
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

    return templates.TemplateResponse(
        "print.html",
        {"request": request, "user": u, "visit": visit, "selected": selected},
    )


# ----------------------------
# PDF (NO arial.ttf dependency)
# ----------------------------
def _pdf_bytes_for_visit(visit: Visit, selected: list[tuple[ChecklistItem, VisitChecklistLine]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    y = h - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "JOB CARD - Stephanou Garage")
    y -= 20

    c.setFont("Helvetica", 10)
    # Remove weird "O&S;" issue by NOT printing any fixed "O&S;" labels at all.
    # Print only what we know.

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
    line("Μοντέλο", getattr(visit, "model", ""))
    line("KM", getattr(visit, "km", ""))

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Εργασίες / Κατηγορίες (επιλεγμένες)")
    y -= 16
    c.setFont("Helvetica", 10)

    for it, ln in selected:
        txt = f"- [{it.category}] {it.name}"
        checked = bool(getattr(ln, "checked", False))
        notes = (getattr(ln, "notes", "") or "").strip()
        pcode = (getattr(ln, "parts_code", "") or "").strip()
        pqty = (getattr(ln, "parts_qty", "") or "").strip()

        extra = []
        if checked:
            extra.append("OK")
        if pcode or pqty:
            extra.append(f"Κωδικός: {pcode}  Ποσ.: {pqty}")
        if notes:
            extra.append(f"Σημ.: {notes}")

        if extra:
            txt += "  |  " + "  |  ".join(extra)

        # page break
        if y < 60:
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 10)

        c.drawString(40, y, txt[:140])
        y -= 14

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Σύνολα")
    y -= 16
    c.setFont("Helvetica", 10)
    line("Total Parts", getattr(visit, "total_parts", ""))
    line("Total Labor", getattr(visit, "total_labor", ""))
    line("Total Amount", getattr(visit, "total_amount", ""))

    c.showPage()
    c.save()
    return buf.getvalue()


@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.id.asc()).all()
    lines = db.query(VisitChecklistLine).filter(VisitChecklistLine.visit_id == visit_id).all()
    line_by_item = {ln.checklist_item_id: ln for ln in lines if getattr(ln, "checklist_item_id", None) is not None}

    selected = []
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

    pdf_bytes = _pdf_bytes_for_visit(visit, selected)

    filename = f"visit_{visit_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ----------------------------
# Backup / Import Backup
# ----------------------------
@app.get("/backup")
def backup_download(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    items = db.query(ChecklistItem).all()
    visits = db.query(Visit).all()
    lines = db.query(VisitChecklistLine).all()

    payload = {
        "version": 1,
        "exported_at": dt.datetime.utcnow().isoformat() + "Z",
        "checklist_items": [
            {"id": it.id, "category": it.category, "name": it.name} for it in items
        ],
        "visits": [
            {c.name: getattr(v, c.name) for c in v.__table__.columns} for v in visits
        ],
        "visit_lines": [
            {c.name: getattr(ln, c.name) for c in ln.__table__.columns} for ln in lines
        ],
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
    if not u:
        return RedirectResponse("/login", status_code=302)

    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    # import checklist items
    for it in payload.get("checklist_items", []):
        category = (it.get("category") or "").strip()
        name = (it.get("name") or "").strip()
        if not category or not name:
            continue
        exists = db.query(ChecklistItem).filter(ChecklistItem.category == category, ChecklistItem.name == name).first()
        if not exists:
            db.add(ChecklistItem(category=category, name=name))
    db.commit()

    # import visits (best effort)
    for v in payload.get("visits", []):
        obj = Visit()
        for k, val in v.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    # import lines (best effort)
    for ln in payload.get("visit_lines", []):
        obj = VisitChecklistLine()
        for k, val in ln.items():
            if hasattr(obj, k):
                setattr(obj, k, val)
        db.add(obj)
    db.commit()

    return RedirectResponse("/", status_code=302)


# ----------------------------
# Reset Test (password protected)
# ----------------------------
@app.post("/reset-test")
def reset_test(request: Request, db: Session = Depends(get_db), code: str = Form("")):
    """
    Διαγράφει ΟΛΑ τα test δεδομένα.
    Θέλει κωδικό για ασφάλεια.
    """
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    RESET_CODE = os.getenv("RESET_CODE", "")
    if not RESET_CODE or code != RESET_CODE:
        return JSONResponse({"ok": False, "error": "Wrong code"}, status_code=403)

    # Delete order: lines -> visits -> checklist
    try:
        db.query(VisitChecklistLine).delete()
    except Exception:
        pass
    try:
        db.query(Visit).delete()
    except Exception:
        pass
    try:
        db.query(ChecklistItem).delete()
    except Exception:
        pass

    db.commit()
    return JSONResponse({"ok": True, "message": "Reset completed"})


# ----------------------------
# Favicon
# ----------------------------
@app.get("/favicon.ico")
def favicon():
    return JSONResponse({"ok": True})
