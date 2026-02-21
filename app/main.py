import os
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from sqlalchemy import or_

from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer, BadSignature

from .db import get_db, engine
from .models import User, ChecklistItem, Visit, VisitChecklistLine
from .pdf_utils import build_jobcard_pdf


app = FastAPI()

templates = Jinja2Templates(directory="app/templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-please-very-secret")
serializer = URLSafeSerializer(SESSION_SECRET, salt="session")


# -----------------------------
# Helpers
# -----------------------------
def set_session(resp: Response, user_id: int):
    token = serializer.dumps({"uid": user_id})
    resp.set_cookie("session", token, httponly=True, samesite="lax")


def clear_session(resp: Response):
    resp.delete_cookie("session")


def current_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token)
        uid = data.get("uid")
        if not uid:
            return None
        return db.query(User).filter(User.id == int(uid)).first()
    except BadSignature:
        return None
    except Exception:
        return None


def require_user(request: Request, db: Session) -> Optional[User]:
    u = current_user(request, db)
    return u


def ensure_admin(db: Session):
    email = os.getenv("ADMIN_EMAIL", "admin@garage.local").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "123456").strip()

    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(email=email, name="Admin", hashed_password=pwd_context.hash(password))
        db.add(u)
        db.commit()


# -----------------------------
# Startup
# -----------------------------
@app.on_event("startup")
def on_startup():
    # create tables (if your db.py already creates them, it's ok)
    try:
        from .models import Base  # noqa
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    # ensure admin user exists
    from .db import SessionLocal
    db = SessionLocal()
    try:
        ensure_admin(db)
    finally:
        db.close()


# -----------------------------
# Auth
# -----------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": None})


@app.post("/login")
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email2 = (email or "").strip().lower()
    u = db.query(User).filter(User.email == email2).first()
    if not u or not pwd_context.verify(password, u.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "user": None, "error": "Λάθος email ή password"},
            status_code=400,
        )

    resp = RedirectResponse("/", status_code=302)
    set_session(resp, u.id)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    clear_session(resp)
    return resp


# -----------------------------
# Index / Visits
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": u, "visits": visits})


@app.post("/visits/new")
def create_visit(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    # create visit
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

    # seed lines from master checklist
    items = db.query(ChecklistItem).order_by(ChecklistItem.category, ChecklistItem.name).all()
    for it in items:
        ln = VisitChecklistLine(
            visit_id=v.id,
            category=it.category,
            item_name=it.name,
            result="OK",
            notes="",
            parts_code="",
            parts_qty=0,
        )
        db.add(ln)
    db.commit()

    return RedirectResponse(f"/visits/{v.id}", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_page(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.visit_id == visit_id
    ).order_by(VisitChecklistLine.id.asc()).all()

    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "user": u, "visit": visit, "lines": lines},
    )


@app.post("/visits/{visit_id}/save_all")
async def save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    # Update visit info
    visit.plate_number = (form.get("plate_number") or "").strip()
    visit.vin = (form.get("vin") or "").strip()
    visit.model = (form.get("model") or "").strip()
    visit.customer_name = (form.get("customer_name") or "").strip()
    visit.phone = (form.get("phone") or "").strip()
    visit.email = (form.get("email") or "").strip()
    visit.km = (form.get("km") or "").strip()
    visit.customer_complaint = (form.get("customer_complaint") or "").strip()

    # Update all checklist lines
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
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return RedirectResponse("/", status_code=302)

    ln = VisitChecklistLine(
        visit_id=visit_id,
        category=(category or "").strip(),
        item_name=(item_name or "").strip(),
        result="OK",
        notes="",
        parts_code="",
        parts_qty=0,
    )
    db.add(ln)

    if add_to_master == "1":
        it = ChecklistItem(category=(category or "").strip(), name=(item_name or "").strip())
        db.add(it)

    db.commit()
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


# -----------------------------
# PDF
# -----------------------------
@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.visit_id == visit_id
    ).order_by(VisitChecklistLine.id.asc()).all()

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
    }

    lines_d = []
    for ln in lines:
        lines_d.append({
            "category": ln.category or "",
            "item_name": ln.item_name or "",
            "result": ln.result or "",
            "parts_code": getattr(ln, "parts_code", "") or "",
            "parts_qty": int(getattr(ln, "parts_qty", 0) or 0),
        })

    try:
        pdf_bytes = build_jobcard_pdf(company, visit_d, lines_d)
        filename = f'job_{visit_d["job_no"]}.pdf'
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        return PlainTextResponse(f"PDF ERROR: {type(e).__name__}: {str(e)}", status_code=500)


# -----------------------------
# Search
# -----------------------------
@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    q2 = (q or "").strip()
    results = []
    if q2:
        like = f"%{q2}%"
        results = db.query(Visit).filter(or_(
            Visit.customer_name.ilike(like),
            Visit.phone.ilike(like),
            Visit.email.ilike(like),
            Visit.plate_number.ilike(like),
            Visit.vin.ilike(like),
            Visit.model.ilike(like),
            Visit.job_no.ilike(like),
        )).order_by(Visit.id.desc()).limit(200).all()

    return templates.TemplateResponse("search.html", {"request": request, "user": u, "q": q2, "results": results})


# -----------------------------
# Checklist (Master) Admin
# -----------------------------
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category, ChecklistItem.name).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "user": u, "items": items})


@app.post("/checklist/{item_id}/update")
def checklist_update(
    item_id: int,
    request: Request,
    category: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        it.category = (category or "").strip()
        it.name = (name or "").strip()
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/{item_id}/delete")
def checklist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)
