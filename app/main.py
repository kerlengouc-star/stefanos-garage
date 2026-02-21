import os
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import User, Company, ChecklistItem, Visit, VisitChecklistLine
from .auth import hash_password, verify_password, sign_session, read_session
from .pdf_utils import build_jobcard_pdf
from .email_utils import send_email_with_pdf

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)


def seed_if_needed(db: Session):
    # Company seed
    if db.query(Company).count() == 0:
        db.add(
            Company(
                name="O&S STEPHANOU LTD",
                address="Michael Paridi 3, Palouriotissa",
                tel="22436990-22436992",
                fax="22437001",
                email="osstephanou@gmail.com",
                vat="10079915R",
                tax_id="12079915T",
            )
        )
        db.commit()

    # Admin seed
    admin_email = os.getenv("ADMIN_EMAIL", "admin@garage.local").strip()
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin12345").strip()
    admin = db.query(User).filter(User.email == admin_email).first()
    if not admin:
        db.add(User(email=admin_email, password_hash=hash_password(admin_pass), role="admin"))
        db.commit()

    # Checklist seed (your list)
    if db.query(ChecklistItem).count() == 0:
        seed_items = [
            ("Service", "Γενικό Σέρβις"),
            ("Service", "Λάδι μηχανής"),
            ("Service", "Λάδι gearbox"),
            ("Φρένα", "Στόπερ μπροστά"),
            ("Φρένα", "Στόπερ πίσω"),
            ("Φρένα", "Φλάντζες μπροστά"),
            ("Φρένα", "Φλάντζες πίσω"),
            ("Φρένα", "Χειρόφρενο"),
            ("Μετάδοση", "Clutch"),
            ("Service", "Oilcooler"),
            ("Ηλεκτρικά", "Starter"),
            ("Ηλεκτρικά", "Δυναμός"),
            ("Μετάδοση", "Αξονάκια"),
            ("A/C", "Αέριο A/C"),
            ("A/C", "Θερμοκρασία"),
            ("Υαλοκαθαριστήρες", "Καθαριστήρες"),
            ("Ηλεκτρικά", "Λάμπες"),
            ("Ψύξη", "Κολάνι"),
            ("Ανάρτηση", "Κόντρα σούστες μπροστά"),
            ("Ανάρτηση", "Κόντρα σούστες πίσω"),
            ("Ελαστικά", "Λάστιχα"),
            ("Ελαστικά", "Γύρισμα ελαστικών"),
            ("Ηλεκτρικά", "Μπαταρία"),
            ("Υαλοκαθαριστήρες", "Μπιτέ καθαριστήρων"),
            ("Ανάρτηση", "Κόντρα σούστες καπό μπροστά"),
            ("Ανάρτηση", "Κόντρα σούστες καπό πίσω"),
        ]
        for cat, name in seed_items:
            db.add(ChecklistItem(category=cat, name=name, active=True, default_show=True))
        db.commit()


@app.on_event("startup")
def _startup():
    from .db import SessionLocal

    db = SessionLocal()
    try:
        seed_if_needed(db)
    finally:
        db.close()


def current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get("session")
    if not token:
        return None
    uid = read_session(token)
    if not uid:
        return None
    return db.query(User).filter(User.id == uid, User.is_active == True).first()


def next_job_no(db: Session) -> str:
    last = db.query(Visit.job_no).order_by(Visit.id.desc()).first()
    if not last or not last[0]:
        return "JC-000001"
    try:
        n = int(last[0].split("-")[1])
        return f"JC-{n+1:06d}"
    except Exception:
        return f"JC-{db.query(Visit).count()+1:06d}"


def recalc_totals(db: Session, visit: Visit):
    parts = Decimal("0")
    labor = Decimal("0")
    total = Decimal("0")
    for ln in visit.lines:
        ln.parts_cost = Decimal(ln.parts_cost or 0)
        ln.labor_cost = Decimal(ln.labor_cost or 0)
        ln.line_total = ln.parts_cost + ln.labor_cost
        parts += ln.parts_cost
        labor += ln.labor_cost
        total += ln.line_total
    visit.total_parts = parts
    visit.total_labor = labor
    visit.total_amount = total
    db.commit()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@app.post("/login")
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.email == email.strip()).first()
    if not u or not verify_password(password, u.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "user": None, "flash": "Λάθος στοιχεία."},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", sign_session(u.id), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(200).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": u, "visits": visits})


@app.get("/visits/new")
def new_visit(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = Visit(job_no=next_job_no(db), date_in=datetime.utcnow(), status="Open")
    db.add(visit)
    db.commit()
    db.refresh(visit)

    items = (
        db.query(ChecklistItem)
        .filter(ChecklistItem.active == True, ChecklistItem.default_show == True)
        .order_by(ChecklistItem.category, ChecklistItem.name)
        .all()
    )
    for it in items:
        db.add(
            VisitChecklistLine(
                visit_id=visit.id,
                checklist_item_id=it.id,
                category=it.category,
                item_name=it.name,
                result="OK",
                parts_cost=0,
                labor_cost=0,
                line_total=0,
            )
        )
    db.commit()
    recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit.id}", status_code=302)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def view_visit(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit.id)
        .order_by(VisitChecklistLine.category, VisitChecklistLine.item_name)
        .all()
    )
    return templates.TemplateResponse(
        "visit.html", {"request": request, "user": u, "visit": visit, "lines": lines}
    )


@app.post("/visits/{visit_id}/update")
def update_visit(
    visit_id: int,
    request: Request,
    plate_number: str = Form(""),
    vin: str = Form(""),
    customer_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    model: str = Form(""),
    km: str = Form(""),
    customer_complaint: str = Form(""),
    db: Session = Depends(get_db),
):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    visit.plate_number = plate_number
    visit.vin = vin
    visit.customer_name = customer_name
    visit.phone = phone
    visit.email = email
    visit.model = model
    visit.km = km
    visit.customer_complaint = customer_complaint
    db.commit()

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


@app.post("/visits/{visit_id}/lines/{line_id}/update")
def update_line(
    visit_id: int,
    line_id: int,
    request: Request,
    result: str = Form("OK"),
    notes: str = Form(""),
    parts_cost: str = Form("0"),
    labor_cost: str = Form("0"),
    db: Session = Depends(get_db),
):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    ln = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.id == line_id, VisitChecklistLine.visit_id == visit_id)
        .first()
    )
    if not ln:
        return RedirectResponse(f"/visits/{visit_id}", status_code=302)

    ln.result = result
    ln.notes = notes
    try:
        ln.parts_cost = Decimal(parts_cost.replace(",", ".") or "0")
    except Exception:
        ln.parts_cost = Decimal("0")
    try:
        ln.labor_cost = Decimal(labor_cost.replace(",", ".") or "0")
    except Exception:
        ln.labor_cost = Decimal("0")

    db.commit()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    recalc_totals(db, visit)
    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


@app.post("/visits/{visit_id}/lines/new")
def add_new_line(
    visit_id: int,
    request: Request,
    category: str = Form(...),
    item_name: str = Form(...),
    add_to_master: str | None = Form(None),
    db: Session = Depends(get_db),
):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    add_master = bool(add_to_master)

    item_id = None
    if add_master:
        it = ChecklistItem(category=category.strip(), name=item_name.strip(), active=True, default_show=True)
        db.add(it)
        db.commit()
        db.refresh(it)
        item_id = it.id

    db.add(
        VisitChecklistLine(
            visit_id=visit_id,
            checklist_item_id=item_id,
            category=category.strip(),
            item_name=item_name.strip(),
            result="OK",
            parts_cost=0,
            labor_cost=0,
            line_total=0,
            add_to_master=add_master,
        )
    )
    db.commit()
    recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)


from fastapi import Response  # αν το έχεις ήδη πιο πάνω, μην το διπλοβάλεις

@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
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

    pdf_bytes = build_jobcard_pdf(company, visit_d, lines_d)

    filename = f'job_{visit_d["job_no"]}.pdf'
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@app.get("/visits/{visit_id}/email", response_class=HTMLResponse)
def email_send(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    if not (visit.email or "").strip():
        return templates.TemplateResponse(
            "base.html",
            {"request": request, "user": u, "flash": "Δεν υπάρχει email πελάτη στο Job Card."},
        )

    company = db.query(Company).first()
    lines = (
        db.query(VisitChecklistLine)
        .filter(VisitChecklistLine.visit_id == visit_id)
        .order_by(VisitChecklistLine.category, VisitChecklistLine.item_name)
        .all()
    )

    company_dict = {
        "name": company.name if company else "",
        "address": company.address if company else "",
        "tel": company.tel if company else "",
        "fax": company.fax if company else "",
        "email": company.email if company else "",
        "vat": company.vat if company else "",
        "tax_id": company.tax_id if company else "",
    }
    visit_dict = {
        "job_no": visit.job_no,
        "date_in": (visit.date_in.strftime("%Y-%m-%d %H:%M") if visit.date_in else ""),
        "plate_number": visit.plate_number,
        "vin": visit.vin,
        "customer_name": visit.customer_name,
        "phone": visit.phone,
        "email": visit.email,
        "model": visit.model,
        "km": visit.km,
        "customer_complaint": visit.customer_complaint,
        "total_amount": float(visit.total_amount or 0),
    }
    lines_list = [
        {
            "item_name": ln.item_name,
            "result": ln.result,
            "parts_cost": float(ln.parts_cost or 0),
            "labor_cost": float(ln.labor_cost or 0),
            "line_total": float(ln.line_total or 0),
        }
        for ln in lines
    ]

    pdf_bytes = build_jobcard_pdf(company_dict, visit_dict, lines_list)

    try:
        send_email_with_pdf(
            to_email=visit.email.strip(),
            subject=f"Job Card {visit.job_no} - {visit.plate_number or ''}",
            body="Σας αποστέλλουμε την κάρτα εργασίας (Job Card) σε PDF.\n\nO&S STEPHANOU LTD",
            pdf_bytes=pdf_bytes,
            filename=f"{visit.job_no}.pdf",
        )
        return templates.TemplateResponse(
            "base.html",
            {"request": request, "user": u, "flash": f"Στάλθηκε email στο {visit.email}."},
        )
    except Exception as e:
        return templates.TemplateResponse(
            "base.html",
            {"request": request, "user": u, "flash": f"Σφάλμα email: {e}"},
            status_code=500,
        )
      
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    ln = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.id == line_id,
        VisitChecklistLine.visit_id == visit_id
    ).first()

    if ln:
        db.delete(ln)
        db.commit()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if visit:
        recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)
    ln = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.id == line_id,
        VisitChecklistLine.visit_id == visit_id
    ).first()

    if ln:
        db.delete(ln)
        db.commit()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if visit:
        recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)
@app.post("/visits/{visit_id}/lines/{line_id}/delete")
def delete_line(visit_id: int, line_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    ln = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.id == line_id,
        VisitChecklistLine.visit_id == visit_id
    ).first()

    if ln:
        db.delete(ln)
        db.commit()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if visit:
        recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)

    
    
        

    ln = db.query(VisitChecklistLine).filter(
        VisitChecklistLine.id == line_id,
        VisitChecklistLine.visit_id == visit_id
    ).first()

    if ln:
        db.delete(ln)
        db.commit()

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if visit:
        recalc_totals(db, visit)

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)
@app.post("/visits/{visit_id}/save_all")
async def save_all(visit_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
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
from sqlalchemy import or_

@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    u = current_user(request, db)
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
        )).order_by(Visit.id.desc()).limit(200).all()

    return templates.TemplateResponse("search.html", {
        "request": request, "user": u, "q": q2, "results": results
    })
@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    items = db.query(ChecklistItem).order_by(ChecklistItem.category, ChecklistItem.name).all()
    return templates.TemplateResponse("checklist.html", {"request": request, "user": u, "items": items})


@app.post("/checklist/{item_id}/update")
def checklist_update(item_id: int,
                     request: Request,
                     category: str = Form(...),
                     name: str = Form(...),
                     db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        it.category = category.strip()
        it.name = name.strip()
        db.commit()
    return RedirectResponse("/checklist", status_code=302)


@app.post("/checklist/{item_id}/delete")
def checklist_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=302)

    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse("/checklist", status_code=302)
