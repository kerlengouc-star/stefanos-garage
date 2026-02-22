from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id = Column(Integer, primary_key=True)
    category = Column(String(200), nullable=False, default="")
    name = Column(String(300), nullable=False, default="")


class Visit(Base):
    __tablename__ = "visits"
    id = Column(Integer, primary_key=True)

    job_no = Column(String(100), default="")
    date_in = Column(DateTime, nullable=True)
    date_out = Column(DateTime, nullable=True)

    plate_number = Column(String(80), default="")
    vin = Column(String(120), default="")
    customer_name = Column(String(200), default="")
    phone = Column(String(80), default="")
    email = Column(String(200), default="")
    model = Column(String(200), default="")
    km = Column(String(50), default="")

    customer_complaint = Column(Text, default="")
    notes_general = Column(Text, default="")

    total_parts = Column(String(50), default="")
    total_labor = Column(String(50), default="")
    total_amount = Column(String(50), default="")
    status = Column(String(50), default="")

    lines = relationship("VisitChecklistLine", back_populates="visit", cascade="all, delete-orphan")


class VisitChecklistLine(Base):
    __tablename__ = "visit_checklist_lines"
    id = Column(Integer, primary_key=True)

    visit_id = Column(Integer, ForeignKey("visits.id"), nullable=False)
    visit = relationship("Visit", back_populates="lines")

    category = Column(String(200), default="")
    item_name = Column(String(300), default="")

    result = Column(String(30), default="OK")  # OK / CHECK / REPAIR
    notes = Column(Text, default="")

    parts_code = Column(String(200), default="")
    parts_qty = Column(Integer, default=0)

    # ✅ NEW: Remember exclusions from print/PDF
    exclude_from_print = Column(Boolean, default=False, nullable=False)
