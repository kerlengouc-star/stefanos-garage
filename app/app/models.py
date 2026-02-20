from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from .db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="staff")  # admin / staff
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Company(Base):
    __tablename__ = "company"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    address = Column(String(255), nullable=True)
    tel = Column(String(255), nullable=True)
    fax = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    vat = Column(String(100), nullable=True)
    tax_id = Column(String(100), nullable=True)

class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id = Column(Integer, primary_key=True)
    category = Column(String(120), nullable=False)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    default_show = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Visit(Base):
    __tablename__ = "visits"
    id = Column(Integer, primary_key=True)
    job_no = Column(String(40), unique=True, index=True, nullable=False)

    date_in = Column(DateTime, default=datetime.utcnow)
    date_out = Column(DateTime, nullable=True)

    plate_number = Column(String(50), nullable=True)
    vin = Column(String(80), nullable=True)
    customer_name = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    model = Column(String(255), nullable=True)
    km = Column(String(50), nullable=True)

    customer_complaint = Column(Text, nullable=True)
    notes_general = Column(Text, nullable=True)

    total_parts = Column(Numeric(10, 2), default=0)
    total_labor = Column(Numeric(10, 2), default=0)
    total_amount = Column(Numeric(10, 2), default=0)

    status = Column(String(50), default="Open")  # Open / Completed / Invoiced

    lines = relationship("VisitChecklistLine", back_populates="visit", cascade="all, delete-orphan")

class VisitChecklistLine(Base):
    __tablename__ = "visit_checklist_lines"
    id = Column(Integer, primary_key=True)

    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    checklist_item_id = Column(Integer, ForeignKey("checklist_items.id"), nullable=True)

    category = Column(String(120), nullable=False)
    item_name = Column(String(255), nullable=False)

    result = Column(String(50), default="OK")  # OK / Θέλει έλεγχο / Αλλαγή
    notes = Column(Text, nullable=True)

    parts_cost = Column(Numeric(10, 2), default=0)
    labor_cost = Column(Numeric(10, 2), default=0)
    line_total = Column(Numeric(10, 2), default=0)

    add_to_master = Column(Boolean, default=False)

    visit = relationship("Visit", back_populates="lines")
    item = relationship("ChecklistItem")
