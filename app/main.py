import os
import io
import json
import datetime as dt
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    StreamingResponse,
    JSONResponse,
    FileResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, Base
from .models import Visit, ChecklistItem, PartMemory

# Keep ORIGINAL utils names used in your project
from .email_utils import send_email_with_pdf
from .pdf_utils import render_visit_pdf


Base.metadata.create_all(bind=engine)

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Serve service worker at site root so it controls ALL pages (scope=/)
@app.get("/sw.js")
def sw_root():
    return FileResponse(
        os.path.join(STATIC_DIR, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# ---------------- DB ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- Diagnostics ----------------
@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py"}

@app.get("/__staticcheck")
def __staticcheck():
    static_exists = os.path.isdir(STATIC_DIR)
    files = []
    if static_exists:
        for root, _, fnames in os.walk(STATIC_DIR):
            for f in fnames:
                rel = os.path.relpath(os.path.join(root, f), STATIC_DIR)
                files.append(rel.replace("\\", "/"))
    return {
        "static_dir": STATIC_DIR,
        "static_exists": static_exists,
        "app_js_exists": os.path.isfile(os.path.join(STATIC_DIR, "app.js")),
        "sw_js_exists": os.path.isfile(os.path.join(STATIC_DIR, "sw.js")),
        "manifest_exists": os.path.isfile(os.path.join(STATIC_DIR, "manifest.webmanifest")),
        "static_files": sorted(files),
    }

@app.get("/__dbinfo")
def __dbinfo(db: Session = Depends(get_db)):
    return {
        "driver": "postgresql" if os.environ.get("DATABASE_URL", "").startswith("postgres") else "sqlite",
        "database_url": os.environ.get("DATABASE_URL", ""),
        "visits_count": db.query(Visit).count(),
        "checklist_count": db.query(ChecklistItem).count(),
        "part_memories_count": db.query(PartMemory).count(),
    }

@app.get("/__tables")
def __tables():
    return {"ok": True}


# ---------------- Helpers ----------------
def group_checklist(db: Session) -> Dict[str, List[ChecklistItem]]:
    items = db.query(ChecklistItem).order_by(ChecklistItem.category.asc(), ChecklistItem.name.asc()).all()
    categories: Dict[str, List[ChecklistItem]] = {}
    for it in items:
        categories.setdefault(it.category, []).append(it)
    return categories


# ---------------- Pages ----------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", db: Session = Depends(get_db)):
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(50).all()
    return templates.TemplateResponse("index.html", {"request": request, "visits": visits, "q": q})


@app.get("/visits/new", response_class=HTMLResponse)
def visit_new_page(request: Request, db: Session = Depends(get_db)):
    categories = group_checklist(db)
    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": None, "categories": categories, "selected_ids": set(), "mode": "all"},
    )


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
    v = Visit(
        customer_name=customer_name,
        phone=phone,
        email=email,
        plate_number=plate_number,
        model=model,
        vin=vin,
        notes=notes,
        date_in=dt.datetime.now(),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return RedirectResponse(url=f"/visits/{v.id}", status_code=303)


@app.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_view(request: Request, visit_id: int, mode: str = "all", db: Session = Depends(get_db)):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return HTMLResponse("Not found", status_code=404)

    categories = group_checklist(db)
    selected_ids = set(v.selected_checklist_ids or [])
    return templates.TemplateResponse(
        "visit.html",
        {"request": request, "visit": v, "categories": categories, "selected_ids": selected_ids, "mode": mode},
    )


@app.post("/visits/{visit_id}/save_all")
def visit_save_all(
    visit_id: int,
    customer_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    plate_number: str = Form(""),
    model: str = Form(""),
    vin: str = Form(""),
    notes: str = Form(""),
    selected_ids: Optional[List[int]] = Form(None),
    db: Session = Depends(get_db),
):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    v.customer_name = customer_name
    v.phone = phone
    v.email = email
    v.plate_number = plate_number
    v.model = model
    v.vin = vin
    v.notes = notes
    v.selected_checklist_ids = selected_ids or []
    db.commit()

    return RedirectResponse(url=f"/visits/{visit_id}?mode=selected", status_code=303)


@app.get("/visits/{visit_id}/print", response_class=HTMLResponse)
def visit_print(request: Request, visit_id: int, db: Session = Depends(get_db)):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return HTMLResponse("Not found", status_code=404)
    categories = group_checklist(db)
    return templates.TemplateResponse("print.html", {"request": request, "visit": v, "categories": categories})


@app.get("/visits/{visit_id}/pdf")
def visit_pdf(visit_id: int, db: Session = Depends(get_db)):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    pdf_bytes = render_visit_pdf(v, db)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")


@app.post("/visits/{visit_id}/email")
def visit_email(visit_id: int, db: Session = Depends(get_db)):
    v = db.query(Visit).filter(Visit.id == visit_id).first()
    if not v:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    ok, message = send_email_with_pdf(v, db)
    return JSONResponse({"ok": ok, "message": message})


@app.get("/checklist", response_class=HTMLResponse)
def checklist_admin(request: Request, db: Session = Depends(get_db)):
    categories = group_checklist(db)
    return templates.TemplateResponse("checklist.html", {"request": request, "categories": categories})


@app.post("/checklist/add")
def checklist_add(category: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    it = ChecklistItem(category=category.strip(), name=name.strip())
    db.add(it)
    db.commit()
    return RedirectResponse(url="/checklist", status_code=303)


@app.post("/checklist/delete/{item_id}")
def checklist_delete(item_id: int, db: Session = Depends(get_db)):
    it = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse(url="/checklist", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(100).all()
    return templates.TemplateResponse("search.html", {"request": request, "visits": visits, "q": q})


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, from_date: str = "", to_date: str = "", q: str = "", db: Session = Depends(get_db)):
    visits = db.query(Visit).order_by(Visit.id.desc()).limit(250).all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "visits": visits, "from_date": from_date, "to_date": to_date, "q": q},
    )


@app.get("/backup")
def backup_export(db: Session = Depends(get_db)):
    visits = db.query(Visit).order_by(Visit.id.asc()).all()
    checklist = db.query(ChecklistItem).order_by(ChecklistItem.id.asc()).all()
    data = {
        "visits": [v.to_dict() for v in visits],
        "checklist": [c.to_dict() for c in checklist],
    }
    return JSONResponse(data)


@app.post("/backup/import")
def backup_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _ = file.file.read()
    return JSONResponse({"ok": True})


@app.post("/reset")
def reset_tests(db: Session = Depends(get_db)):
    return JSONResponse({"ok": True})
